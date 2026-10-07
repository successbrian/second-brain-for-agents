"""Tests for knowledge_hygiene.py — fully offline via a stubbed psycopg2.

The ``kh`` fixture (tests/conftest.py) imports the module against a fake
connection that never touches Postgres; every SQL statement is captured as
text on ``conn.cursor_.executed`` and rows are scripted by the test.
"""
import json

import pytest


def _conn(kh):
    _mod, _factory, conn = kh
    return conn


def executed(kh):
    return _conn(kh).cursor_.executed


def last_executed(kh):
    return executed(kh)[-1]


# ---------------------------------------------------------------- table name
def test_validate_table_name_passes_plain(kh):
    mod, _f, _c = kh
    assert mod.validate_table_name("second_brain") == "second_brain"
    assert mod.validate_table_name("facts_2026") == "facts_2026"
    assert mod.validate_table_name("_hygiene") == "_hygiene"


def test_validate_table_name_defaults(kh):
    mod, _f, _c = kh
    mod.TABLE = "second_brain"
    assert mod.validate_table_name(None) == "second_brain"
    assert mod.validate_table_name("") == "second_brain"


@pytest.mark.parametrize("bad", [
    "second_brain; DROP TABLE facts",
    "facts table",
    "1facts",
    "facts-table",
    "tab;'",
    "facts\"; DROP",
])
def test_validate_table_name_rejects_unsafe(kh, bad):
    mod, _f, _c = kh
    with pytest.raises(ValueError):
        mod.validate_table_name(bad)


# ---------------------------------------------------------------- expiration
def test_expire_live_updates_and_commits(kh):
    mod, factory, conn = kh
    conn.cursor_.rowcount = 3
    mod.expire(table="second_brain", conn_factory=factory)
    sql = last_executed(kh)
    assert "UPDATE second_brain SET confidence = 'expired'" in sql
    assert "expires_at <= now()" in sql
    assert "confidence != 'expired'" in sql
    assert conn.commits == 1
    assert conn.cursor_.closed and conn.closed


def test_expire_dry_run_selects_not_updates(kh):
    mod, factory, conn = kh
    conn.cursor_.fetchone_row = (5,)
    mod.expire(dry_run=True, table="second_brain", conn_factory=factory)
    sql = last_executed(kh)
    assert "SELECT count(*) FROM second_brain" in sql
    assert "UPDATE" not in sql
    assert conn.commits == 0  # dry run never commits


def test_expire_default_table_from_module(kh):
    mod, factory, conn = kh
    mod.TABLE = "brain"
    conn.cursor_.rowcount = 2
    mod.expire(conn_factory=factory)
    assert "UPDATE brain SET confidence = 'expired'" in last_executed(kh)


# ---------------------------------------------------------------- dedupe list
def test_duplicate_topics_returns_sorted(kh):
    mod, factory, conn = kh
    conn.cursor_.fetchall_rows = [("topic-a", 3), ("topic-b", 2)]
    out = mod.duplicate_topics(table="second_brain", conn_factory=factory)
    assert out == [("topic-a", 3), ("topic-b", 2)]
    sql = last_executed(kh)
    assert "GROUP BY 1 HAVING count(*) > 1 ORDER BY 2 DESC" in sql
    assert "WHERE confidence != 'expired'" in sql


def test_duplicate_topics_empty(kh):
    mod, factory, conn = kh
    conn.cursor_.fetchall_rows = []
    assert mod.duplicate_topics(conn_factory=factory) == []


# ---------------------------------------------------------------- reconcile
def test_reconcile_builds_window_sql(kh):
    mod, factory, conn = kh
    conn.cursor_.rowcount = 4
    n = mod.reconcile_duplicates(apply=True, table="second_brain", conn_factory=factory)
    assert n == 4
    sql = last_executed(kh)
    assert sql.startswith("UPDATE second_brain SET confidence='expired'")
    assert "first_value(id) OVER (PARTITION BY topic" in sql
    assert "'high' THEN 3" in sql and "'low' THEN 1" in sql
    assert "dedupe-kept" in sql
    assert conn.commits == 1


def test_reconcile_keeps_highest_confidence_rank(kh):
    mod, factory, conn = kh
    mod.reconcile_duplicates(apply=True, table="t", conn_factory=factory)
    sql = last_executed(kh)
    # high must outrank medium/low/expired; ordering checked in the CASE
    order = sql[sql.index("ORDER BY"):]
    assert order.index("'high' THEN 3") < order.index("'medium' THEN 2")
    assert order.index("'medium' THEN 2") < order.index("'low' THEN 1")
    assert "updated_at DESC, id DESC" in sql


def test_reconcile_dry_run_counts_only(kh):
    mod, factory, conn = kh
    conn.cursor_.fetchone_row = (2,)
    n = mod.reconcile_duplicates(apply=True, dry_run=True, table="t", conn_factory=factory)
    assert n == 2
    sql = last_executed(kh)
    assert "SELECT count(*) FROM" in sql
    assert "UPDATE" not in sql
    assert conn.commits == 0


def test_reconcile_without_apply_mutates_nothing(kh):
    mod, factory, conn = kh
    n = mod.reconcile_duplicates(apply=False, table="t", conn_factory=factory)
    assert n == 0
    assert conn.commits == 0
    assert all("UPDATE" not in s for s in executed(kh))


# ------------------------------------------------------------- dedupe wrapper
def test_dedupe_lists_only_without_apply(kh):
    mod, factory, conn = kh
    conn.cursor_.fetchall_rows = [("x", 2)]
    mod.dedupe(apply=False, table="t", conn_factory=factory)
    # exactly one SELECT (the listing), no UPDATE
    assert len(executed(kh)) == 1
    assert "UPDATE" not in last_executed(kh)


def test_dedupe_apply_reconciles(kh):
    mod, factory, conn = kh
    conn.cursor_.fetchall_rows = [("x", 2)]
    conn.cursor_.rowcount = 1
    mod.dedupe(apply=True, table="t", conn_factory=factory)
    assert len(executed(kh)) == 2
    assert executed(kh)[0].startswith("SELECT")
    assert executed(kh)[1].startswith("UPDATE")


# ---------------------------------------------------------------- report
def test_report_text_output(kh, capsys):
    mod, factory, conn = kh
    conn.cursor_.fetchall_rows = [("fact", "high", 4), ("rule", "low", 2)]
    mod.report(table="t", conn_factory=factory)
    out = capsys.readouterr().out
    assert "fact" in out and "high" in out and "4" in out
    assert '{"' not in out  # not json


def test_report_json_output(kh, capsys):
    mod, factory, conn = kh
    conn.cursor_.fetchall_rows = [("fact", "high", 4)]
    mod.report(as_json=True, table="t", conn_factory=factory)
    data = json.loads(capsys.readouterr().out)
    assert data["category_x_confidence"] == [
        {"category": "fact", "confidence": "high", "count": 4}
    ]


# ---------------------------------------------------------------- cli
def test_cli_no_flags_returns_1(kh):
    mod, _f, _c = kh
    assert mod.main([]) == 1


def test_cli_bad_table_exits_2(kh, capsys, monkeypatch):
    mod, _f, _c = kh
    # A hostile table name must surface as a clean ValueError -> exit code 2,
    # not a crash. Force the validation failure inside the CLI path.
    def hostile(table=None, default=mod.TABLE):
        raise ValueError("invalid table name 'x; DROP TABLE facts'")

    monkeypatch.setattr(mod, "validate_table_name", hostile)
    rc = mod.main(["--report"])
    assert rc == 2
    assert "error:" in capsys.readouterr().err


def test_cli_report_runs(kh, capsys):
    mod, factory, conn = kh
    conn.cursor_.fetchall_rows = [("fact", "medium", 1)]
    rc = mod.main(["--report"])
    assert rc == 0
    assert "fact" in capsys.readouterr().out