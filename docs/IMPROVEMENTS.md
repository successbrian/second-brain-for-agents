# Daily Improvements

Every day, this repo gets a little better. Each entry: what changed and why.

## 2026-10-17
- README flags table now documents `--dry-run` (modifier for `--expire`: previews how many facts would expire without changing anything) — the flag existed in code and the module docstring but the README's table omitted it; docs now match the CLI surface. Survey: `py_compile` clean, no TODO/FIXME/HACK markers, all imports used, module docstrings follow PURPOSE/WHY/CALLED BY/NOTES, `second_brain.py` functions all documented. `knowledge_hygiene.py`'s internal helpers (`_conn`, `expire`, `dedupe`, `report`) have no function docstrings — left alone as internal-by-design, module docstring documents the CLI.

## 2026-10-08
- Nothing qualified for a safe improvement: `py_compile` clean, no TODO/FIXME/HACK markers, the module docstring already follows PURPOSE/WHY/CALLED BY/NOTES, README flags verified against the argparse definitions (all present), runtime artifacts gitignored. Left the repo untouched rather than manufacture churn.

## 2026-10-07
- Nothing qualified for a safe improvement: `py_compile` clean, no TODO/FIXME/HACK markers, the module docstring already follows PURPOSE/WHY/CALLED BY/NOTES, README flags verified against the argparse definitions (all present). Left the repo untouched rather than manufacture churn.

## 2026-09-27
- Seeded this log — the daily improvements job tracks every change here from now on.

## 2026-09-28
- Nothing qualified for a safe improvement: `py_compile` clean, no TODO/FIXME/HACK markers, module docstring follows PURPOSE/WHY/CALLED BY/NOTES, README matches the tool's flags. Left the repo untouched rather than manufacture churn.

## 2026-09-29
- Nothing qualified for a safe improvement: `py_compile` clean, no TODO/FIXME/HACK markers, module docstring follows PURPOSE/WHY/CALLED BY/NOTES, README matches the tool's flags. Left the repo untouched rather than manufacture churn.

## 2026-09-30
- Nothing qualified for a safe improvement: `py_compile` clean, no TODO/FIXME/HACK markers, module docstring follows PURPOSE/WHY/CALLED BY/NOTES, README matches the tool's flags, `__pycache__/` untracked. Left the repo untouched rather than manufacture churn.

## 2026-10-01
- Added `.gitignore` covering `__pycache__/` and `*.py[cod]`; removed the stray untracked `__pycache__/` from the working tree — regenerable bytecode was cluttering the checkout (same cleanup successbrian-os got on 2026-09-28).
- Survey: `py_compile` clean, no TODO/FIXME/HACK markers, module docstring follows PURPOSE/WHY/CALLED BY/NOTES, README matches the tool's flags — nothing else qualified, left the rest untouched.
## 2026-10-02
- Nothing qualified for a safe improvement: `py_compile` clean, no TODO/FIXME/HACK markers, no unused imports, module docstring follows PURPOSE/WHY/CALLED BY/NOTES, README matches the tool's flags. Left the repo untouched rather than manufacture churn.

## 2026-10-03
- Nothing qualified for a safe improvement: `py_compile` clean, no TODO/FIXME/HACK markers, no unused imports, module docstring follows PURPOSE/WHY/CALLED BY/NOTES, README matches the tool's flags. Left the repo untouched rather than manufacture churn.

## 2026-10-04
- Nothing qualified for a safe improvement: `py_compile` clean, no TODO/FIXME/HACK markers, module docstring follows PURPOSE/WHY/CALLED BY/NOTES, README matches the tool's flags, runtime artifacts gitignored. Left the repo untouched rather than manufacture churn.

## 2026-10-05
- Nothing qualified for a safe improvement: `py_compile` clean, no TODO/FIXME/HACK markers, module docstring follows PURPOSE/WHY/CALLED BY/NOTES, README matches the tool's flags, runtime artifacts gitignored. Left the repo untouched rather than manufacture churn.

## 2026-10-06
- Nothing qualified for a safe improvement: `py_compile` clean, no TODO/FIXME/HACK markers, no unused imports, module docstrings follow PURPOSE/WHY/CALLED BY/NOTES, README current. Left the repo untouched rather than manufacture churn.

## 2026-10-09
- Nothing qualified for a safe improvement: py_compile clean, no TODO/FIXME/HACK comments, no unused imports, module docstring and README current. Survey only, no churn.

## 2026-10-10
- Nothing qualified for a safe improvement: `py_compile` clean, no TODO/FIXME/HACK markers, module docstring follows PURPOSE/WHY/CALLED BY/NOTES, README flags match argparse, `__pycache__/` gitignored and working tree clean. Survey only, no churn.

## 2026-10-11
- Nothing qualified for a safe improvement: `py_compile` clean, no TODO/FIXME/HACK markers, module docstring follows PURPOSE/WHY/CALLED BY/NOTES, README flags match argparse, `__pycache__/` gitignored and working tree clean. Survey only, no churn.

## 2026-10-12
- Wrapped all three DB functions (expire, dedupe, report) with try/except psycopg2.Error blocks — on connection failure or query error the tool now prints a clean "error (func): {message}" to stderr and exits cleanly instead of dumping a raw psycopg2 traceback. This matters because the hygiene tool runs unattended via cron; a raw stack trace in cron mail looks like a crash to the operator when it's just a bad network to Postgres.

## 2026-10-13
- Nothing qualified for a safe improvement: `py_compile` clean, no TODO/FIXME/HACK markers, no unused imports, module docstring follows PURPOSE/WHY/CALLED BY/NOTES, today's pull (error-handling rework of knowledge_hygiene.py) already documented, README current. Survey only, no churn.

## 2026-10-14
- Removed 2 unused imports from second_brain.py: `timedelta` (only `datetime` is used) and `RealDictCursor` (cursors are plain `c.cursor()`). Verified zero references, py_compile clean. Why it matters: the client module landed 2026-10-13; dead imports in a fresh module invite the next reader to assume a feature (timedelta math, dict cursors) that doesn't exist.
- README: added a "Python client" section documenting second_brain.py (insert_fact / query / get_recent / get_by_confidence / update_confidence / count with a usage example) — the README previously only covered knowledge_hygiene.py even though the client module is the agent-facing API. Doc-only fix; function table checked against actual signatures.

## 2026-10-16
- README: added `upsert_fact(topic, content, ...)` and `search(pattern, match_field?, ...)` rows to the Python client function table — both landed 2026-10-15 (upsert_fact with the UNIQUE-topic constraint, search with ILIKE topic / LIKE content partial matching) but the table documented only the six Oct-13 functions. Doc-only fix; signatures copied verbatim from the code. Why it matters: the two newest functions are the agent-facing ones most likely to be reached for first (idempotent writes, fuzzy lookup); a table that omits them understates the API.
- Survey: `py_compile` clean, no TODO/FIXME/HACK, all imports used, module docstrings present.
