# Phase 0: foundation, dedup and retry-safe scraping

Date: 2026-10-18. Status: approved in chat; implemented on branch `testing_env`.

## Goal

Make the existing pipeline (Codeforces API sync -> scraper) safe to build on, and add
Div1A / Div2C deduplication, before any tutorial finder or hint generator exists.

Out of scope for this phase: contest protector, tutorial finder, hint generator, public
API / extension, deployment, and actually running the backfill. Those need either a later
design or an operator (you) with a backup in hand.

## Decisions carried over from the chat

- Dedup approach **A**: candidates are problems with the same normalized name whose
  contests share a `start_time`; auto-merge only when the normalized statement hash also
  matches; candidates whose hash differs go to a review report and are never auto-merged.
- Statement-only hints are allowed (original ask: "tutorial, if any exists"), so hints get
  a `grounded_in_tutorial` flag.
- Merge `interactive_problem_specifications` into `problem_specifications`.
- Unrated problems are `NULL`, not `-1`.
- RLS is already enabled on every table (confirmed by the user), so no RLS statements.

## Schema (migrations/)

`000_baseline_schema.sql` is the pre-migration schema. It runs on an empty database (to build a staging project); never on production.

### `001_foundation.sql` (additive, one transaction, safe to apply before the code)

- Defaults: `problems.stage_status = 'DISCOVERED'`, `problems.created_at/updated_at = now()`,
  `hints.created_at = now()`, `tutorials.scraped_at = now()`. `contests.start_time` loses its
  `now()` default (a contest start time must always be supplied).
- `problems.rating = -1` becomes `NULL`.
- `memory_limit_ms` -> `memory_limit_mb` on both spec tables (the value is MB).
- CHECK constraints on `problems.stage_status` (adds `DUPLICATE`), `contests.phase`,
  `contests.type`, and `hints.hint_level` (1-5).
- `hints`: `UNIQUE (problem_id, hint_level)` so regeneration is an upsert, and
  `grounded_in_tutorial boolean NOT NULL DEFAULT false`.
- `problems`: `canonical_problem_id` (self FK), `scrape_attempts smallint NOT NULL DEFAULT 0`,
  `last_error text`; constraint `stage_status = 'DUPLICATE'` iff `canonical_problem_id IS NOT NULL`;
  a row cannot be its own canonical.
- `problem_specifications`: `statement_hash text`, `interaction_specification text`, and
  `output_specification` becomes nullable with `CHECK (num_nonnulls(output_specification,
  interaction_specification) >= 1)`.
- Every child FK to `problems(id)` is recreated with `ON DELETE CASCADE`, followed by an
  assertion that none was missed. `canonical_problem_id` is deliberately plain (no cascade): deleting
  a canonical problem while its duplicates remain must fail loudly.

### `002_merge_interactive_specs_and_drop_archive.sql` (destructive; back up first)

- Copies `interactive_problem_specifications` into `problem_specifications` (its old
  `output_specification` held the Interaction section, so it moves to `interaction_specification`),
  asserts every row arrived, then drops `interactive_problem_specifications` and
  `sample_tests_ARCHIEVED`.

Deviation from the chat: the schema half of the merge (new column, relaxed NOT NULL) moved into 001 so the
new scraper works as soon as 001 is applied; only the data copy and the drops wait for 002.
The CHECK is "at least one" rather than "exactly one" so a page that has both an Output and an
Interaction section does not lose either.

## Code

- `src/utils/toProblemRow.ts` (new, pure) + `src/core/database/insertProblem.ts`: upsert only
  metadata columns (`id, contest_id, index, name, rating, tags, updated_at`). Existing
  `stage_status` and `created_at` are never in the payload, so they cannot be reset; new rows get the DB
  defaults. The status pre-fetch and the `updateExistingMetadata` flag are removed.
- `src/core/database/insertContest.ts`: set `last_check_at` on every sync.
- `src/core/database/deleteProblem.ts`, `admin/ProblemWithTargetedTagRemover.py`: rely on cascades
  (duplicates are deleted before canonical rows in the admin script).
- `src/services/scraper/`:
  - `errors.py`: `ScrapingValidationError` (permanent) and `TransientScrapeError` (retryable).
  - `problemScraper.py`: classifies HTTP outcomes. 404 -> permanent. Network errors, 403, 429, 5xx and any
    other non-200 -> transient. A 200 page with no `.problem-statement` (Cloudflare challenge,
    maintenance page) -> transient. Browser-style User-Agent.
  - `problemParser.py`: the former `parse_problem_details_strictly`, now one function that detects
    interactive problems from the page (an "Interaction" section inside `.problem-statement`), and returns
    a specs dict matching the merged table plus `statement_hash`. Parsing rules are otherwise unchanged.
  - `mainChecker.py`: the single batch loop (replaces `mainInteractiveChecker.py`). Per run: at most
    `--limit` problems (default 1000, Supabase's page cap), `--delay` seconds between requests (default 2.0),
    ordered by `scrape_attempts` then `id`. Transient failure: `scrape_attempts += 1`, `last_error` set,
    stays `DISCOVERED`; at 5 attempts it becomes `FAILED`. Validation failure: `FAILED` with `last_error`.
    The run aborts after 5 consecutive transient failures (a block should stop the run, not be hammered).
- `src/utils/statementHash.py`: `normalizeText` (NFKC, strip zero-width characters, collapse whitespace)
  and `computeStatementHash`. The hash covers the statement, input, output and interaction sections plus
  the time and memory limits; notes and samples are excluded. Stricter on limits on purpose: a Div2 variant
  with different limits goes to review instead of silently sharing hints.
- `src/workers/dedup/dedupPlanner.py` (pure) and `dedupProblems.py` (database I/O, dry-run by default,
  `--apply` to write, `--report PATH` for the review CSV). It backfills missing hashes, groups candidates,
  and links duplicates. The canonical member is the one furthest along the pipeline, then the lowest
  `contest_id`, then the lowest `id`, so a problem that already has hints is never demoted.

## Verification

Offline only: `python -m unittest discover -s tests` (parser fixtures, scraper HTTP classification with a
mocked `requests`, hashing, dedup planning) and `node --test tests/` (the problem-row mapping, including
that `stage_status` and `created_at` are absent from the payload). Nothing in this phase was run against
Codeforces or Supabase.

## Rollout runbook (operator)

1. Back up the database.
2. Apply `001_foundation.sql`. Then use the new code (the old code writes `memory_limit_ms`, which 001 renames).
3. Apply `002_...` once you are happy; it is the only destructive step.
4. Run `insertContest`/`insertProblem`, then `mainChecker`, repeating until `DISCOVERED` is empty.
5. Review `FAILED` rows (`last_error` now says why), spot-check ~10 stored statements for LaTeX and line breaks.
6. Run `dedupProblems` (dry-run), read the plan and the review report, then rerun with `--apply`.
