"""
TEST FIXTURES

Sets up a clean test database for second_brain integration tests.
All tests run against a real PostgreSQL instance (local by default).

DB config via env vars (same as second_brain.py / knowledge_hygiene.py):
  SB_DB_HOST  (default: /var/run/postgresql)
  SB_DB_PORT  (default: 5432)
  SB_DB_NAME  (default: postgres)
  SB_DB_USER  (default: current OS user)
  SB_TABLE    (default: test_second_brain)

Run: pytest tests/ -v
"""
import os
import re
import pytest
import psycopg2


def _split_sql_statements(sql: str) -> list[str]:
    """Split SQL into statements, respecting dollar-quoted strings and -- comments.

    Two bugs from naive split(';'):
    1. PostgreSQL $tag$ ... $tag$ dollar-quoted blocks (function bodies) contain ;
    2. -- line comments may contain ;
    This function tracks dollar-quote entry/exit and skips -- comments correctly.
    """
    statements: list[str] = []
    current: list[str] = []
    i = 0
    n = len(sql)
    in_dollar = False

    while i < n:
        ch = sql[i]

        if in_dollar:
            if ch == "$":
                j = i + 1
                tag_chars = ""
                while j < n and sql[j] != "$" and sql[j].isalnum():
                    tag_chars += sql[j]
                    j += 1
                if j < n and sql[j] == "$" and tag_chars:
                    current.append(sql[i : j + 1])
                    i = j + 1
                    in_dollar = False
                    continue
            current.append(ch)
            i += 1
            continue

        if ch == "$":
            j = i + 1
            tag_chars = ""
            while j < n and sql[j] != "$" and sql[j].isalnum():
                tag_chars += sql[j]
                j += 1
            if j < n and sql[j] == "$" and tag_chars:
                current.append(sql[i : j + 1])
                i = j + 1
                in_dollar = True
                continue

        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                current.append(sql[i])
                i += 1
            continue

        if ch == ";":
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue

        current.append(ch)
        i += 1

    final = "".join(current).strip()
    if final:
        statements.append(final)

    return statements


@pytest.fixture(scope="session")
def test_db():
    """Create a fresh test database and schema, yield connection, then cleanup."""
    table = os.environ.get("SB_TABLE", "test_second_brain")
    events_table = os.environ.get("SB_EVENTS_TABLE", "test_second_brain_events")

    # Connect to postgres (not our test DB) to create the test DB
    host = os.environ.get("SB_DB_HOST", "/var/run/postgresql")
    port = os.environ.get("SB_DB_PORT", "5432")
    user = os.environ.get("SB_DB_USER", os.environ.get("USER", "successbrian"))
    dbname = os.environ.get("SB_DB_NAME", "postgres")

    conn = psycopg2.connect(host=host, port=port, dbname=dbname, user=user)
    conn.autocommit = True
    cur = conn.cursor()

    # Create test database
    cur.execute("SELECT 1 FROM pg_database WHERE datname = 'sb_test'")
    if not cur.fetchone():
        cur.execute("CREATE DATABASE sb_test")
    cur.close()
    conn.close()

    # Connect to test DB and create schema
    conn = psycopg2.connect(
        host=host, port=port, dbname="sb_test", user=user
    )
    cur = conn.cursor()

    # Read schema
    schema_path = os.path.join(os.path.dirname(__file__), "..", "schema.sql")
    with open(schema_path) as f:
        schema_sql = f.read()

    # Execute schema (handles CREATE TABLE IF NOT EXISTS, indexes, triggers, functions)
    # Must use dollar-quote-aware splitter — naive split(';') breaks
    # fn_second_brain_audit() because BEGIN...END contains semicolons.
    statements = _split_sql_statements(schema_sql)
    for stmt in statements:
        # Replace table names for test namespace
        test_stmt = stmt.replace("second_brain", table).replace("second_brain_events", events_table)
        try:
            cur.execute(test_stmt)
        except Exception as e:
            print(f"Warning: {e}")

    conn.commit()
    cur.close()
    conn.close()

    # Yield — tests run here
    yield {
        "host": host,
        "port": port,
        "dbname": "sb_test",
        "user": user,
        "table": table,
        "events_table": events_table,
    }

    # Cleanup
    conn = psycopg2.connect(
        host=host, port=port, dbname=dbname, user=user,
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f'DROP TABLE IF EXISTS {table} CASCADE')
    cur.execute(f'DROP TABLE IF EXISTS {events_table} CASCADE')
    cur.execute("DROP DATABASE sb_test")
    cur.close()
    conn.close()


@pytest.fixture
def env_patch(test_db, monkeypatch):
    """Set env vars so second_brain module uses test DB."""
    monkeypatch.setenv("SB_DB_HOST", test_db["host"])
    monkeypatch.setenv("SB_DB_PORT", str(test_db["port"]))
    monkeypatch.setenv("SB_DB_NAME", test_db["dbname"])
    monkeypatch.setenv("SB_DB_USER", test_db["user"])
    monkeypatch.setenv("SB_TABLE", test_db["table"])
    monkeypatch.setenv("SB_EVENTS_TABLE", test_db["events_table"])
    return test_db


@pytest.fixture
def clean_table(env_patch):
    """Ensure table is empty before each test."""
    from second_brain import TABLE, EVENTS_TABLE
    import psycopg2
    import os

    conn = psycopg2.connect(
        host=os.environ["SB_DB_HOST"],
        port=int(os.environ["SB_DB_PORT"]),
        dbname=os.environ["SB_DB_NAME"],
        user=os.environ["SB_DB_USER"],
    )
    cur = conn.cursor()
    cur.execute(f"DELETE FROM {EVENTS_TABLE}")
    cur.execute(f"DELETE FROM {TABLE}")
    conn.commit()
    cur.close()
    conn.close()
    return env_patch
