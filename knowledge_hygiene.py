#!/usr/bin/env python3
"""
PURPOSE: Soft-expire, dedupe, and report on an agent's second-brain knowledge store.
WHY: A knowledge store rots three ways: facts go stale past their expires_at,
    duplicate topics accumulate, and operational noise buries the signal.
    Without scheduled hygiene, stale facts silently poison agent reasoning.
    Soft-expire flips confidence to 'expired' (reversible, never deletes),
    so the cleanup stays quarantine-not-delete safe.
CALLED BY: Sunday/night shift ecosystem cleanup, heartbeat check-ins.
    Run on k11-alpha where the second brain lives (see env example below).
NOTES:
    - --expire is deliberately non-destructive: it marks facts, it never
      deletes rows. Use --dry-run first when unsure.
    - --dedupe lists duplicate topics; --dedupe --apply soft-expires every
      copy EXCEPT the highest-confidence one per topic (high > medium > low,
      tie-broken by most-recently-updated, then by id). Like --expire this
      quarantines rather than deletes, so it honours the non-destructive rule.
    - --apply is the only flag that mutates data besides --expire; pair it
      with --dry-run to preview.
    - Default DB config targets generic local Postgres; override via env.
    - The report() command previously crashed on NULL category rows
      (2026-09-28 fix: COALESCE in the GROUP BY).
    - All SQL table names are validated against an identifier whitelist
      before interpolation, so a hostile SB_TABLE cannot inject SQL.

A knowledge store decays three ways: facts go stale, topics get duplicated, and
operational noise buries the signal. This tool keeps it clean.

  --expire   soft-expire facts whose expires_at has passed
  --dedupe   list duplicate topics; with --apply, soft-expire all but the
             highest-confidence copy of each
  --report   summarize the store by category + confidence
  --apply    make --dedupe actually reconcile (without it, --dedupe only lists)
  --json     emit machine-readable JSON instead of human tables (report/dedupe)
  --dry-run  with --expire or --dedupe --apply: print counts, change nothing

DB config via env vars (defaults to unix-socket local peer auth):
  SB_DB_HOST  (default: /var/run/postgresql)
  SB_DB_PORT  (default: 5432)
  SB_DB_NAME  (default: postgres)
  SB_DB_USER  (default: current user)
  SB_TABLE    (default: second_brain)

SuccessBrian deployment (ecosystem_central on k11-alpha):
  SB_DB_HOST=localhost SB_DB_NAME=ecosystem_central SB_DB_USER=successbrian \\
    python3 knowledge_hygiene.py --expire

Requires: psycopg2  (pip install psycopg2-binary)
"""
import argparse
import json
import os
import re
import sys

import psycopg2

DB = dict(
    host=os.environ.get("SB_DB_HOST", "/var/run/postgresql"),
    port=int(os.environ.get("SB_DB_PORT", "5432")),
    dbname=os.environ.get("SB_DB_NAME", "postgres"),
    user=os.environ.get("SB_DB_USER", os.environ.get("USER", "")),
)
TABLE = os.environ.get("SB_TABLE", "second_brain")

# Confidence rank used to pick the copy that survives a dedupe.
_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1, "expired": 0}
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _default_connect():
    return psycopg2.connect(**DB)


def _conn(conn_factory=None):
    return conn_factory() if conn_factory is not None else _default_connect()


def validate_table_name(table=None, default=None):
    """Return a safe identifier or raise ValueError.

    Table names can't be bound as SQL parameters in psycopg2, so they are
    interpolated directly into statements. This whitelist keeps a hostile
    SB_TABLE from injecting arbitrary SQL.
    """
    if not table:
        table = default or TABLE
    if not _IDENTIFIER_RE.match(table):
        raise ValueError(
            f"invalid table name {table!r}: only [A-Za-z_][A-Za-z0-9_]* allowed; "
            "set SB_TABLE to a plain identifier"
        )
    return table


def expire(dry_run=False, table=None, conn_factory=None):
    """Soft-expire facts whose expires_at has passed. Never deletes rows."""
    table = validate_table_name(table)
    c = _conn(conn_factory)
    cur = c.cursor()
    where = ("WHERE expires_at IS NOT NULL AND expires_at <= now() "
             "AND confidence != 'expired'")
    if dry_run:
        cur.execute(f"SELECT count(*) FROM {table} {where}")
        n = cur.fetchone()[0]
        print(f"would expire: {n} facts past their expires_at (dry run)")
    else:
        cur.execute(f"UPDATE {table} SET confidence = 'expired' {where}")
        n = cur.rowcount
        c.commit()
        print(f"expired: {n} facts past their expires_at")
    cur.close()
    c.close()
    return n


def duplicate_topics(table=None, conn_factory=None):
    """Return [(topic, count)] for duplicate topics, highest count first."""
    table = validate_table_name(table)
    c = _conn(conn_factory)
    cur = c.cursor()
    cur.execute(
        f"SELECT COALESCE(topic, '(no topic)'), count(*) FROM {table} "
        f"WHERE confidence != 'expired' "
        f"GROUP BY 1 HAVING count(*) > 1 ORDER BY 2 DESC"
    )
    rows = cur.fetchall()
    cur.close()
    c.close()
    return [(topic, n) for topic, n in rows]


def reconcile_duplicates(apply=False, dry_run=False, table=None, conn_factory=None):
    """Reconcile duplicate topics in one statement.

    For each topic with more than one non-expired fact, keep the highest-
    confidence copy (high > medium > low, tie-broken by most-recently-updated,
    then by largest id) and soft-expire every other copy. Marks the kept id on
    the expired rows so the decision is auditable. Quarantines, never deletes.
    """
    table = validate_table_name(table)
    c = _conn(conn_factory)
    cur = c.cursor()
    order = "CASE confidence " + " ".join(
        f"WHEN '{k}' THEN {v}" for k, v in _CONFIDENCE_RANK.items()
    ) + " ELSE 0 END DESC, updated_at DESC, id DESC"
    select_kept = (
        f"SELECT id, first_value(id) OVER (PARTITION BY topic "
        f"ORDER BY {order}) AS kept_id FROM {table} "
        f"WHERE confidence != 'expired' AND topic IS NOT NULL"
    )
    dup_cyl = f"FROM ({select_kept}) w JOIN {table} t ON t.id = w.id WHERE w.id <> w.kept_id"
    if dry_run:
        cur.execute(f"SELECT count(*) {dup_cyl}")
        n = cur.fetchone()[0]
        print(f"would reconcile: {n} duplicate copies past their kept copy (dry run)")
    else:
        if not apply:
            print("would reconcile: (use --apply to soft-expire duplicates)")
            cur.close()
            c.close()
            return 0
        cur.execute(
            f"UPDATE {table} SET confidence='expired', "
            f"verification = COALESCE(t.verification, '') || ' | dedupe-kept=' || w.kept_id {dup_cyl}"
        )
        n = cur.rowcount
        c.commit()
        print(f"reconciled: {n} duplicate copies soft-expired")
    cur.close()
    c.close()
    return n


def dedupe(apply=False, dry_run=False, table=None, conn_factory=None):
    """List duplicate topics; with --apply, reconcile them too."""
    dups = duplicate_topics(table=table, conn_factory=conn_factory)
    for topic, n in dups:
        print(f"dup topic ({n}x): {topic}")
    print(f"duplicate topics: {len(dups)}")
    if apply and dups:
        reconcile_duplicates(apply=True, dry_run=dry_run,
                             table=table, conn_factory=conn_factory)


def report(as_json=False, table=None, conn_factory=None):
    """Summarize the store by category x confidence (expired excluded)."""
    table = validate_table_name(table)
    c = _conn(conn_factory)
    cur = c.cursor()
    cur.execute(
        f"SELECT COALESCE(category, '(uncategorized)'), "
        f"COALESCE(confidence, '(none)'), count(*) FROM {table} "
        f"WHERE confidence != 'expired' GROUP BY 1, 2 ORDER BY 1, 2"
    )
    rows = cur.fetchall()
    cur.close()
    c.close()
    if as_json:
        print(json.dumps({"category_x_confidence": [
            {"category": cat, "confidence": conf, "count": n}
            for cat, conf, n in rows
        ]}))
        return
    for cat, conf, n in rows:
        print(f"{cat:20s} {conf:10s} {n}")


def _run_cli(argv=None):
    ap = argparse.ArgumentParser(description="Second-brain hygiene")
    ap.add_argument("--expire", action="store_true")
    ap.add_argument("--dedupe", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--apply", action="store_true",
                    help="with --dedupe: soft-expire all but the highest-confidence copy")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON (report/dedupe)")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --expire / --dedupe --apply: show counts, change nothing")
    a = ap.parse_args(argv)
    if not (a.expire or a.dedupe or a.report):
        ap.print_help()
        return 1
    if a.expire:
        expire(dry_run=a.dry_run)
    if a.dedupe:
        dedupe(apply=a.apply, dry_run=a.dry_run)
    if a.report:
        report(as_json=a.json)
    return 0


def main(argv=None):
    """Console-script entry point. Returns a process exit code."""
    try:
        return _run_cli(argv)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())