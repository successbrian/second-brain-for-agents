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
    - Default DB config targets generic local Postgres; override via env.
    - The report() command previously crashed on NULL category rows
      (2026-09-28 fix: COALESCE in the GROUP BY).

A knowledge store decays three ways: facts go stale, topics get duplicated, and
operational noise buries the signal. This tool keeps it clean.

  --expire   soft-expire facts whose expires_at has passed
  --dedupe   list duplicate topics (keep the highest-confidence copy)
  --report   summarize the store by category + confidence
  --dry-run  with --expire: print how many facts WOULD expire, change nothing

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
import os
import sys

import psycopg2

DB = dict(
    host=os.environ.get("SB_DB_HOST", "/var/run/postgresql"),
    port=int(os.environ.get("SB_DB_PORT", "5432")),
    dbname=os.environ.get("SB_DB_NAME", "postgres"),
    user=os.environ.get("SB_DB_USER", os.environ.get("USER", "")),
)
TABLE = os.environ.get("SB_TABLE", "second_brain")


def _conn():
    return psycopg2.connect(**DB)


def expire(dry_run=False):
    c = _conn()
    cur = c.cursor()
    where = (f"WHERE expires_at IS NOT NULL AND expires_at <= now() "
             f"AND confidence != 'expired'")
    if dry_run:
        cur.execute(f"SELECT count(*) FROM {TABLE} {where}")
        n = cur.fetchone()[0]
        print(f"would expire: {n} facts past their expires_at (dry run)")
    else:
        cur.execute(f"UPDATE {TABLE} SET confidence = 'expired' {where}")
        n = cur.rowcount
        c.commit()
        print(f"expired: {n} facts past their expires_at")
    cur.close()
    c.close()


def dedupe():
    c = _conn()
    cur = c.cursor()
    cur.execute(
        f"SELECT COALESCE(topic, '(no topic)'), count(*) FROM {TABLE} "
        f"WHERE confidence != 'expired' "
        f"GROUP BY 1 HAVING count(*) > 1 ORDER BY 2 DESC"
    )
    rows = cur.fetchall()
    for topic, n in rows:
        print(f"dup topic ({n}x): {topic}")
    cur.close()
    c.close()
    print(f"duplicate topics: {len(rows)}")


def report():
    c = _conn()
    cur = c.cursor()
    cur.execute(
        f"SELECT COALESCE(category, '(uncategorized)'), "
        f"COALESCE(confidence, '(none)'), count(*) FROM {TABLE} "
        f"WHERE confidence != 'expired' GROUP BY 1, 2 ORDER BY 1, 2"
    )
    rows = cur.fetchall()
    for cat, conf, n in rows:
        print(f"{cat:20s} {conf:10s} {n}")
    cur.close()
    c.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Second-brain hygiene")
    ap.add_argument("--expire", action="store_true")
    ap.add_argument("--dedupe", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --expire: show count without changing anything")
    a = ap.parse_args()
    if not (a.expire or a.dedupe or a.report):
        ap.print_help()
        sys.exit(1)
    if a.expire:
        expire(dry_run=a.dry_run)
    if a.dedupe:
        dedupe()
    if a.report:
        report()
