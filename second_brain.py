#!/usr/bin/env python3
"""
PURPOSE: A reusable PostgreSQL client for the second-brain knowledge store.
WHY: Agents need a simple API to insert, query, and retrieve facts from the
    second-brain table. This module encapsulates all SQL in one place.
CALLED BY: Any agent that needs to consult or update the second brain.
NOTES:
    - DB config via env vars (same as knowledge_hygiene.py).
    - All functions return plain Python types for easy consumption.
    - Safe to import from any agent code.

Requires: psycopg2  (pip install psycopg2-binary)

Usage:
    from second_brain import insert_fact, query, get_recent
    insert_fact("market_status", "rule", "HN shows 403 on Reddit", confidence="high")
    for row in query("market_status", category="rule"):
        print(row["content"])
"""
import os
import sys
from datetime import datetime
from typing import Optional

import psycopg2


DB = dict(
    host=os.environ.get("SB_DB_HOST", "/var/run/postgresql"),
    port=os.environ.get("SB_DB_PORT", "5432"),
    dbname=os.environ.get("SB_DB_NAME", "postgres"),
    user=os.environ.get("SB_DB_USER", os.environ.get("USER", "")),
)
TABLE = os.environ.get("SB_TABLE", "second_brain")

# Confidence ordering for sorting results.
CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2, "expired": 3}


def _conn():
    """Open a connection and return a cursor-ready context."""
    return psycopg2.connect(**DB)  # type: ignore[call-arg]


def _upsert_updated():
    """Return the SET clause for updating the updated_at timestamp."""
    return "updated_at = now()"


def insert_fact(
    topic: str,
    content: str,
    category: str = "fact",
    confidence: str = "medium",
    source: Optional[str] = None,
    verification: Optional[str] = None,
    expires_at: Optional[datetime] = None,
    tags: Optional[list[str]] = None,
) -> int:
    """
    Insert a new fact into the second brain.

    Args:
        topic: Subject of the fact (e.g. "market_status", "pricing_rule").
        content: The fact itself.
        category: "fact", "rule", "research", etc. (default: "fact").
        confidence: "low", "medium", "high" (default: "medium").
        source: Where the fact came from.
        verification: How it was verified.
        expires_at: When this fact expires (NULL = never).
        tags: Freeform tags for indexing.

    Returns:
        The new row's id.
    """
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(
            f"""
            INSERT INTO {TABLE}
                (topic, category, content, confidence, source,
                 verification, expires_at, tags)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (topic, category, content, confidence, source, verification,
             expires_at, tags),
        )
        row_id = cur.fetchone()["id"]
        c.commit()
        cur.close()
        c.close()
        return row_id
    except psycopg2.Error as e:
        print(f"error (insert_fact): {e}", file=sys.stderr)
        raise


def query(
    topic: str,
    category: Optional[str] = None,
    min_confidence: str = "low",
    limit: int = 50,
) -> list[dict]:
    """
    Query facts by topic.

    Args:
        topic: The topic to search for (exact match on topic column).
        category: Optional category filter.
        min_confidence: Minimum confidence level to return.
            Order: high > medium > low > expired.
        limit: Max rows to return.

    Returns:
        List of dicts representing matching rows.
    """
    try:
        c = _conn()
        cur = c.cursor()
        sql = f"SELECT * FROM {TABLE} WHERE topic = %s AND confidence != 'expired'"
        params: list = [topic]
        if category:
            sql += " AND category = %s"
            params.append(category)
        # Filter out expired (already done above) but enforce ordering
        sql += f" ORDER BY CASE confidence"
        for level, order in CONFIDENCE_ORDER.items():
            sql += f" WHEN '{level}' THEN {order}"
        sql += " END, created_at DESC"
        sql += " LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        c.close()
        return rows
    except psycopg2.Error as e:
        print(f"error (query): {e}", file=sys.stderr)
        return []


def get_recent(hours: int = 24, limit: int = 50) -> list[dict]:
    """
    Get the most recent non-expired facts.

    Args:
        hours: Look back this many hours (default: 24).
        limit: Max rows to return.

    Returns:
        List of dicts representing recent facts.
    """
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(
            f"""
            SELECT * FROM {TABLE}
            WHERE updated_at > now() - interval '{hours} hours'
              AND confidence != 'expired'
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        c.close()
        return rows
    except psycopg2.Error as e:
        print(f"error (get_recent): {e}", file=sys.stderr)
        return []


def get_by_confidence(
    confidence: str,
    category: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """
    Get all facts at a given confidence level.

    Args:
        confidence: "high", "medium", or "low".
        category: Optional category filter.
        limit: Max rows to return.

    Returns:
        List of dicts matching the confidence level.
    """
    try:
        c = _conn()
        cur = c.cursor()
        sql = f"SELECT * FROM {TABLE} WHERE confidence = %s AND confidence != 'expired'"
        params: list = [confidence]
        if category:
            sql += " AND category = %s"
            params.append(category)
        sql += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        c.close()
        return rows
    except psycopg2.Error as e:
        print(f"error (get_by_confidence): {e}", file=sys.stderr)
        return []


def update_confidence(
    sb_id: int,
    new_confidence: str,
    verification: Optional[str] = None,
) -> bool:
    """
    Update a fact's confidence and optionally its verification field.

    Args:
        sb_id: The second_brain row id.
        new_confidence: New confidence level.
        verification: Optional verification text to update.

    Returns:
        True if a row was updated, False if not found.
    """
    try:
        c = _conn()
        cur = c.cursor()
        if verification:
            cur.execute(
                f"""
                UPDATE {TABLE}
                SET confidence = %s, verification = %s,
                    {_upsert_updated()}
                WHERE id = %s
                """,
                (new_confidence, verification, sb_id),
            )
        else:
            cur.execute(
                f"""
                UPDATE {TABLE}
                SET confidence = %s, {_upsert_updated()}
                WHERE id = %s
                """,
                (new_confidence, sb_id),
            )
        changed = cur.rowcount > 0
        c.commit()
        cur.close()
        c.close()
        return changed
    except psycopg2.Error as e:
        print(f"error (update_confidence): {e}", file=sys.stderr)
        return False


def count() -> dict:
    """
    Get a summary count of the knowledge store.

    Returns:
        Dict with counts by confidence level.
    """
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(
            f"""
            SELECT confidence, count(*)
            FROM {TABLE}
            GROUP BY confidence
            ORDER BY confidence
            """
        )
        result = {r["confidence"]: r["count"] for r in cur.fetchall()}
        cur.close()
        c.close()
        return result
    except psycopg2.Error as e:
        print(f"error (count): {e}", file=sys.stderr)
        return {}


if __name__ == "__main__":
    import json
    # Quick self-test when run directly
    print("second_brain client — env check")
    for key in ("SB_DB_HOST", "SB_DB_PORT", "SB_DB_NAME", "SB_DB_USER", "SB_TABLE"):
        val = os.environ.get(key, "<default>")
        print(f"  {key} = {val}")
    print(f"TABLE = {TABLE}")
    print("count():", json.dumps(count(), indent=2))
    print("get_recent(1):", json.dumps(get_recent(hours=1, limit=3), indent=2))
