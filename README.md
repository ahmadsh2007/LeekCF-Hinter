# LeekCF-Hinter

A pipeline that builds progressive, spoiler-safe hints for Codeforces problems. It syncs problems from the
Codeforces API, scrapes each statement, finds duplicates (the same problem in Div. 1 and Div. 2), and will
turn statements and editorials into graded hints served to a browser extension.
The full plan is in `Codeforces Hinter Architecture Blueprint copy.docx`; the Phase 0 design is in
`docs/superpowers/specs/`.

## How a problem moves through the pipeline

`problems.stage_status`:

| Status | Meaning | Set by |
|---|---|---|
| `DISCOVERED` | Known from the Codeforces API, not scraped yet | `insertProblem.ts` |
| `SCRAPED_WAITING_FOR_CONTEST` | Statement and samples stored | `mainChecker.py` |
| `DUPLICATE` | Same problem as `canonical_problem_id` (e.g. Div. 1 A and Div. 2 C) | `dedupProblems.py` |
| `WAITING_FOR_TUTORIAL`, `TUTORIAL_FOUND`, `HINTS_GENERATED` | Later stages, not built yet | |
| `FAILED` | Gave up; the reason is in `problems.last_error` | `mainChecker.py` |

Not built yet: the contest protector (never serve hints while a contest is live), the tutorial finder, the
hint generator, and the public API / extension.

## Setup

- Node 24+ (TypeScript runs natively) and Python 3.14.
- `npm install`
- `python -m venv venv && venv/bin/pip install -r requirements.txt`
- `config/.env` (not committed) needs `SUPABASE_DATABASE_URL` and `SUPABASE_DATABASE_SECRET_KEY`.
- `config/IGNORE_THESE_CONTESTS` lists contest ids that are never added to the database.

## Database migrations

SQL files in `migrations/` are applied by hand (Supabase SQL editor), in order. They are not run by any script.

1. **Take a backup first.**
2. `001_foundation.sql` is additive and runs in one transaction. Apply it before running the scripts below:
   the old scripts write `memory_limit_ms`, which it renames to `memory_limit_mb`.
3. `002_merge_interactive_specs_and_drop_archive.sql` is destructive (drops two tables) and refuses to run unless
   every row was merged. Apply it only after 001.

`000_baseline_schema.sql` is the schema before any migration. It runs on an empty database, so use it to build a
staging project; never run it on production.

## Running

Run everything from the repository root.

```bash
# 1. Sync contests, then problems, from the Codeforces API (new problems start as DISCOVERED)
node src/core/database/insertProblem.ts

# 2. Scrape DISCOVERED problems; repeat until none are left. Stops early if Codeforces starts blocking.
venv/bin/python -u -m src.services.scraper.mainChecker --limit 1000 --delay 2

# 3. Find duplicates. Dry run by default: read the plan, then add --apply.
venv/bin/python -u -m src.workers.dedup.dedupProblems --report dedup_review.csv
venv/bin/python -u -m src.workers.dedup.dedupProblems --apply

# Remove problems and contests that were added to config/IGNORE_THESE_CONTESTS
node src/core/database/deleteProblem.ts
```

Failed problems keep the reason in `last_error`. Network problems and blocks are retried on later runs
(up to 5 attempts); pages that fail validation are `FAILED` immediately.
The emergency scripts in `src/core/database/admin/` are described in their own README.

## Tests

Offline: nothing touches Codeforces or Supabase.

```bash
venv/bin/python -m unittest discover -s tests
node --test tests/toProblemRow.test.ts
```
