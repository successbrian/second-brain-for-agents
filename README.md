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

## License

MIT — do whatever you want with it. See LICENSE file.
