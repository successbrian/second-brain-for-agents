"""Offline test support: stub psycopg2 with a fake that records SQL.

knowledge_hygiene.py does `import psycopg2` at top level, so we inject a fake
module into sys.modules BEFORE importing it. No Postgres connection is ever
made; every query is captured as text and rows are scripted per test.

The module is imported ONCE (Python caches it), so the fixture rebinds
``_default_connect`` to a fresh FakeConn per test — this is what the CLI path
(stick-default conn factory) and direct calls (explicit ``conn_factory=``)
both flow through, keeping every test isolated to its own connection.
"""
import sys
import types

import pytest


class FakeCursor:
    def __init__(self):
        self.executed = []
        self.fetchall_rows = []
        self.fetchone_row = (0,)
        self.rowcount = 0
        self.closed = False

    def execute(self, sql):
        self.executed.append(sql)

    def fetchall(self):
        return self.fetchall_rows

    def fetchone(self):
        return self.fetchone_row

    def close(self):
        self.closed = True


class FakeConn:
    def __init__(self):
        self.cursor_ = FakeCursor()
        self.commits = 0
        self.closed = False

    def cursor(self):
        return self.cursor_

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


@pytest.fixture
def kh(monkeypatch):
    """Import knowledge_hygiene, binding a fresh FakeConn as the default.

    Returns (module, conn_factory, conn). ``conn_factory()`` yields the same
    helper FakeConn the module ALSO uses as its default, so tests can read
    back ``conn.cursor_.executed`` after a call regardless of entry point.
    """
    conn = FakeConn()
    fake = types.ModuleType("psycopg2")
    fake.connect = lambda **kw: conn
    sys.modules["psycopg2"] = fake

    import knowledge_hygiene as kh

    # Keep module-import once but rebind the CLI/default connection each test.
    kh._default_connect = lambda: conn
    factory = lambda: conn  # noqa: E731
    return kh, factory, conn