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


def upsert_fact(
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
    Insert or update a fact by topic. If a row with the same topic exists,
    update its content, confidence, verification, expires_at, and tags in place
    (created_at is preserved). Returns the row's id (new or existing).

    Args:
        topic: Subject of the fact (used for the upsert key).
        content: The fact itself.
        category: "fact", "rule", "research", etc. (default: "fact").
        confidence: "low", "medium", "high" (default: "medium").
        source: Where the fact came from.
        verification: How it was verified.
        expires_at: When this fact expires (NULL = never).
        tags: Freeform tags for indexing.

    Returns:
        The row's id (new or existing).
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
            ON CONFLICT (topic) DO UPDATE SET
                content = EXCLUDED.content,
                category = EXCLUDED.category,
                confidence = EXCLUDED.confidence,
                source = EXCLUDED.source,
                verification = EXCLUDED.verification,
                expires_at = EXCLUDED.expires_at,
                tags = EXCLUDED.tags,
                {_upsert_updated()}
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
        print(f"error (upsert_fact): {e}", file=sys.stderr)
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


def search(
    pattern: str,
    category: Optional[str] = None,
    min_confidence: str = "low",
    match_field: str = "topic",
    limit: int = 50,
) -> list[dict]:
    """
    Search facts by partial topic or content match.

    Args:
        pattern: Substring to search for (ILIKE for topic, LIKE for content).
        category: Optional category filter.
        min_confidence: Minimum confidence level (order: high > medium > low > expired).
        match_field: "topic" (default, ILIKE partial match) or "content" (LIKE partial).
        limit: Max rows to return.

    Examples:
        search("market")  -> finds "market_status", "market_trend", etc.
        search("403", match_field="content")  -> finds facts containing "403"
    """
    try:
        c = _conn()
        cur = c.cursor()
        if match_field == "content":
            sql = f"SELECT * FROM {TABLE} WHERE content LIKE %s AND confidence != 'expired'"
            params: list = [f"%{pattern}%"]
        else:
            sql = f"SELECT * FROM {TABLE} WHERE topic ILIKE %s AND confidence != 'expired'"
            params: list = [f"%{pattern}%"]
        if category:
            sql += " AND category = %s"
            params.append(category)
        sql += f" ORDER BY CASE confidence"
        for level, order in CONFIDENCE_ORDER.items():
            sql += f" WHEN '{level}' THEN {order}"
        sql += " END, created_at DESC LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        c.close()
        return rows
    except psycopg2.Error as e:
        print(f"error (search): {e}", file=sys.stderr)
        return []


def count() -> dict:
    """
    Return row counts grouped by category × confidence (non-expired).

    Returns:
        Dict keyed by category, each value a dict keyed by confidence level
        with the row count.  Example: {"rule": {"high": 5, "medium": 3}, "fact": {"low": 2}}.
    """
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(
            f"""
            SELECT category, confidence, count(*)::int
            FROM {TABLE}
            WHERE confidence != 'expired'
            GROUP BY 1, 2
            ORDER BY 1, 2
            """
        )
        result: dict = {}
        for category, confidence, n in cur.fetchall():
            result.setdefault(category, {})[confidence] = n
        cur.close()
        c.close()
        return result
    except psycopg2.Error as e:
        print(f"error (count): {e}", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# Event audit log — second_brain_events client
# ---------------------------------------------------------------------------

EVENTS_TABLE = os.environ.get("SB_EVENTS_TABLE", "second_brain_events")


def events_append(
    sb_id: int,
    event_type: str,
    old_confidence: Optional[str] = None,
    new_confidence: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> int:
    """
    Append an audit event to the second_brain_events table.

    Args:
        sb_id: The second_brain row id this event references.
        event_type: "insert", "update", "expire", or "delete".
        old_confidence: Previous confidence level (for update/expire events).
        new_confidence: New confidence level (for update/expire events).
        metadata: Arbitrary JSONB payload for additional context.

    Returns:
        The new event row id.

    Examples:
        events_append(42, "expire", old_confidence="high", new_confidence="expired")
        events_append(42, "insert", metadata={"source": "scout"})
    """
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(
            f"""
            INSERT INTO {EVENTS_TABLE}
                (sb_id, event_type, old_confidence, new_confidence, metadata)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (sb_id, event_type, old_confidence, new_confidence, metadata),
        )
        event_id = cur.fetchone()["id"]
        c.commit()
        cur.close()
        c.close()
        return event_id
    except psycopg2.Error as e:
        print(f"error (events_append): {e}", file=sys.stderr)
        return -1


def events_read(
    sb_id: Optional[int] = None,
    event_type: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """
    Read audit events, optionally filtered by sb_id and/or event_type.

    Args:
        sb_id: Filter to events for this second_brain row.
        event_type: Filter to this event type only.
        limit: Max rows to return.

    Returns:
        List of event dicts ordered newest-first.
    """
    try:
        c = _conn()
        cur = c.cursor()
        sql = f"SELECT * FROM {EVENTS_TABLE} WHERE 1=1"
        params: list = []
        if sb_id is not None:
            sql += " AND sb_id = %s"
            params.append(sb_id)
        if event_type is not None:
            sql += " AND event_type = %s"
            params.append(event_type)
        sql += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        c.close()
        return rows
    except psycopg2.Error as e:
        print(f"error (events_read): {e}", file=sys.stderr)
        return []


def events_archive(older_than_days: int = 365) -> int:
    """
    Soft-archive events older than the given number of days.

    Moves the confidence of old events to 'archived' so they stay queryable
    but don't clutter the active audit log. The data is never deleted.

    Args:
        older_than_days: Archive events older than this many days.

    Returns:
        Number of events archived.
    """
    try:
        c = _conn()
        cur = c.cursor()
        cur.execute(
            f"""
            UPDATE {EVENTS_TABLE}
            SET metadata = COALESCE(metadata, '{{}}'::jsonb) ||
                           jsonb_build_object('archived_at', now()::text)
            WHERE created_at < now() - interval '{older_than_days} days'
            AND metadata->'archived_at' IS NULL
            """,
        )
        n = cur.rowcount
        c.commit()
        cur.close()
        c.close()
        print(f"archived: {n} events older than {older_than_days} days")
        return n
    except psycopg2.Error as e:
        print(f"error (events_archive): {e}", file=sys.stderr)
        return -1
