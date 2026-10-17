# Second-Brain-for-Agents

A reusable, PostgreSQL-backed knowledge store for AI agents. Every fact carries
**confidence**, **expiry**, and **verification** — so stale or unverified knowledge
can't silently poison your agent's reasoning.

## Why

Agents accumulate knowledge fast. Without structure, that knowledge rots:
facts go stale, duplicate topics compete, and operational noise buries the
signal. The second brain solves this with three mechanisms:

1. **Confidence scoring** (`low | medium | high | expired`) — each fact carries
   a trust level that downstream consumers can gate on.
2. **Expiry** (`expires_at`) — facts auto-expire past their shelf life. Run
   `knowledge_hygiene.py --expire` to soft-mark them.
3. **Verification** (`verification`) — every fact records *how* it was verified,
   so you can trace a claim back to its source.

## Quick start

```bash
# Set up the table (one-time)
psql -d your_db -f schema.sql

# Run hygiene (configure via env vars or defaults)
python3 knowledge_hygiene.py --report
python3 knowledge_hygiene.py --expire
python3 knowledge_hygiene.py --dedupe
```

## Python client

`second_brain.py` is a reusable client for agent code — same env vars, same
table, no CLI needed:

```python
from second_brain import insert_fact, query, get_recent

insert_fact("market_status", "rule", "HN shows 403 on Reddit", confidence="high")
for row in query("market_status", category="rule"):
    print(row["content"])
```

| Function | What it does |
|----------|--------------|
| `insert_fact(topic, content, ...)` | Insert a fact, returns the new row id |
| `upsert_fact(topic, content, ...)` | Insert or update by UNIQUE topic, returns the row id |
| `query(topic, category?, min_confidence?, limit?)` | Facts by exact topic, confidence-ordered, expired excluded |
| `get_recent(hours=24, limit=50)` | Newest facts in the window |
| `get_by_confidence(confidence, limit?)` | Facts at one confidence level |
| `update_confidence(id, confidence)` | Re-grade a fact |
| `search(pattern, match_field?, category?, min_confidence?, limit?)` | Partial topic/content match (match_field: "topic" ILIKE or "content" LIKE) |
| `count()` | Row counts by category × confidence |

## Environment variables

| Variable     | Default                    | Purpose                          |
|------------- |---------------------------|----------------------------------|
| `SB_DB_HOST` | `/var/run/postgresql`     | PostgreSQL host / socket path    |
| `SB_DB_PORT` | `5432`                     | PostgreSQL port                  |
| `SB_DB_NAME` | `postgres`                 | Database name                    |
| `SB_DB_USER` | current OS user            | Database user                    |
| `SB_TABLE`   | `second_brain`             | Table name (customizable)        |

Requires `psycopg2` (`pip install psycopg2-binary`).

## The three hygiene operations

| Flag       | What it does                                                        |
|----------- |---------------------------------------------------------------------|
| `--report` | Summarizes the store by `category × confidence` — your knowledge at a glance |
| `--expire` | Soft-marks facts past `expires_at` as `expired` (won't delete, just downgrades confidence) |
| `--dedupe` | Lists duplicate topics ranked by count — pick the highest-confidence copy and remove the rest |
| `--dry-run` | Modifier for `--expire`: prints how many facts WOULD expire without changing anything |

## Architecture

```
[Agent produces fact] → INSERT into second_brain (confidence=medium)
       ↓
[Verification pipeline] → UPDATE verification + confidence=high
       ↓
[Hygiene cron] → --expire (stale → expired), --dedupe (dupes flagged)
       ↓
[Consumer queries] → filter WHERE confidence != 'expired'
```

## Schema

**second_brain** — knowledge entries. Every fact carries `confidence`
(low | medium | high | expired), `expires_at`, and `verification`.

| Column       | Type        | Purpose                              |
|------------- |------------ |--------------------------------------|
| id           | BIGSERIAL   | Primary key                          |
| topic        | TEXT NOT NULL | Subject (dups allowed; hygiene reconciles) |
| category     | TEXT NOT NULL | fact | rule | research | ...         |
| content      | TEXT NOT NULL | The fact itself                     |
| confidence   | TEXT        | low | medium | high | expired        |
| source       | TEXT        | Where it came from                   |
| verification | TEXT        | How it was verified                  |
| expires_at   | TIMESTAMPTZ | NULL = never; >90d = ask first       |
| tags         | TEXT[]      | Freeform indexing                    |
| created_at   | TIMESTAMPTZ | Row creation time                    |
| updated_at   | TIMESTAMPTZ | Last modification time               |

**second_brain_events** — append-only audit log (never deleted).
Records every insert, update, and expire operation for provenance
tracing. Indexed on `sb_id` and `event_type`.

Indexes: `topic`, `tags` (GIN), `expires_at`, `category+confidence`.

## License

MIT — do whatever you want with it. See LICENSE file.
