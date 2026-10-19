# LeekCF-Hinter

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

A pipeline that builds progressive, spoiler-safe hints for Codeforces problems and serves them through a public,
read-only API. It syncs problems from the Codeforces API, scrapes each statement, finds duplicates (the same problem
in Div. 1 and Div. 2), waits until a contest is over, finds the official tutorial, asks an AI model (Gemini, Claude, ...) for
graded hints (2 to 5, depending on the problem), and serves them.
The full plan is in `Codeforces Hinter Architecture Blueprint copy.docx`; the designs are in `docs/superpowers/specs/`.
To try everything on a throwaway Supabase project, follow `docs/staging-runbook.md`. To put the API online for free, see
`docs/launch.md`; to run the pipeline automatically, `docs/automation.md`; for a Vertex AI model, `docs/vertex-setup.md`;
for a Google Cloud deployment, `deploy/README.md`. A draft announcement and funding appeal is in `docs/announcement-draft.md`.

## How a problem moves through the pipeline

`problems.stage_status`:

| Status | Meaning | Set by |
|---|---|---|
| `DISCOVERED` | Known from the Codeforces API, not scraped yet | `insertProblem.ts` |
| `SCRAPED_WAITING_FOR_CONTEST` | Statement and samples stored | `mainChecker.py` |
| `DUPLICATE` | Same problem as `canonical_problem_id` (e.g. Div. 1 A and Div. 2 C) | `dedupProblems.py` |
| `WAITING_FOR_TUTORIAL` | The contest is over by 2 hours; looking for the tutorial | `contestProtector.py` |
| `TUTORIAL_FOUND` | The official tutorial text is stored | `findTutorials.py` |
| `HINTS_GENERATED` | Five hints are stored and can be served | `generateHints.py` |
| `FAILED` | Gave up; the reason is in `problems.last_error` | `mainChecker.py` |

Not built: the browser extension. Hints are never generated for, or served from, a contest that is not over.

## Setup

- Node 24+ (TypeScript runs natively) and Python 3.14.
- `npm install`
- `python -m venv venv && venv/bin/pip install -r requirements.txt`
- `config/.env` (not committed) needs `SUPABASE_DATABASE_URL` and `SUPABASE_DATABASE_SECRET_KEY`. The hint
  generator also needs `ANTHROPIC_API_KEY`; it uses Claude Opus 5.5 at high effort unless `ANTHROPIC_MODEL` /
  `ANTHROPIC_EFFORT` say otherwise. `LLM_PROVIDER` can also be `gemini` (Google AI Studio: `GEMINI_API_KEY`, `GEMINI_MODEL`, optional
  `GEMINI_THINKING_LEVEL`) or `vertex` (Gemini 4 Argon on Vertex AI: `VERTEX_PROJECT`, `GOOGLE_APPLICATION_CREDENTIALS`; see
  `docs/vertex-setup.md`), or a comma-separated chain such as `vertex,gemini` that moves on to the next model for good when
  the first one stops working (e.g. the free credit is used up). What it costs:
  `docs/cost-estimate.md`. The public API uses `SUPABASE_PUBLISHABLE_KEY` instead and refuses a secret key.
- `config/IGNORE_THESE_CONTESTS` lists contest ids that are never added to the database.
- To point any script at another project (e.g. a staging Supabase project) without touching `config/.env`, set
  `ENV_FILE`: `ENV_FILE=~/leekcf-env/staging.env venv/bin/python -u -m src.services.scraper.mainChecker`.
  Every script prints `Supabase target: <host>` first, so you can see which project it is about to use.

## Database migrations

SQL files in `migrations/` are applied by hand (Supabase SQL editor), in order. They are not run by any script.

1. **Take a backup first.**
2. `001_foundation.sql` is additive and runs in one transaction. Apply it before running the scripts below:
   the old scripts write `memory_limit_ms`, which it renames to `memory_limit_mb`.
3. `002_merge_interactive_specs_and_drop_archive.sql` is destructive (drops two tables) and refuses to run unless
   every row was merged. Apply it only after 001.
4. `003_pipeline_state.sql` adds `problems.hint_attempts`, one tutorial per problem, and lets interactive problems that have no Input section be stored. Additive. Apply it before the scraper.
5. `004_public_hints_view.sql` creates `public_hints`, the only thing the public API can read: it returns hints only
   when the contest is over by 2 hours. Additive.

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

# 4. Move problems whose contest is over (finished + 2 hours) on to WAITING_FOR_TUTORIAL
venv/bin/python -u -m src.workers.contest_monitor.contestProtector            # add --dry-run to only look

# 5. Find the official tutorials (newest contests first; --limit counts contests)
venv/bin/python -u -m src.workers.tutorial_finder.findTutorials --limit 50

# 6. Generate hints. Try --dry-run first: it calls the model, prints the hints and the tokens/cost used, writes nothing.
venv/bin/python -u -m src.workers.hint_generator.generateHints --dry-run --limit 5
venv/bin/python -u -m src.workers.hint_generator.generateHints --limit 20
#    --include-without-tutorial also covers problems whose tutorial never turned up (hints are marked ungrounded)

# 7. Serve the hints (needs SUPABASE_DATABASE_URL and SUPABASE_PUBLISHABLE_KEY)
node src/api/server.ts
#    The server documents itself: open http://localhost:8080/ in a browser, or GET /v1/openapi.json

# All of the above, every day, automatically: see docs/automation.md
scripts/daily.sh

# The one-off backlog of a freshly loaded database (run both, side by side, and leave them; both are restartable):
ENV_FILE=~/leekcf-env/staging.env caffeinate -i scripts/scrape-all.sh      # scrapes every problem, ~16 per minute
ENV_FILE=~/leekcf-env/staging.env caffeinate -i scripts/backfill.sh        # tutorials + hints as problems arrive; stops by itself

# Remove problems and contests that were added to config/IGNORE_THESE_CONTESTS
node src/core/database/deleteProblem.ts
```

Failed problems keep the reason in `last_error`. Network problems and blocks are retried on later runs
(up to 5 attempts); pages that fail validation are `FAILED` immediately.
The emergency scripts in `src/core/database/admin/` are described in their own README.

## The public API

Read-only, no key needed. The running server documents itself: `GET /` (a readable page) and `GET /v1/openapi.json`
(OpenAPI 3.1, usable with any API tool). Set `PUBLIC_BASE_URL` so the examples show your address.



```
GET /v1/problems/{contestId}/{index}/hints     e.g. /v1/problems/1944/C/hints
GET /v1/health
```

It returns 2 to 5 hint levels, easiest first (`level`, `content` in Markdown with `$...$` math), the problem's name, rating and tags,
whether the hints are `groundedInTutorial`, and `duplicateOf` when the problem shares hints with its Div. 1 / Div. 2 twin.
Statements and editorials are never served. A problem with no public hints is a plain `404`, whatever the reason
(unknown, not processed yet, contest not over). Responses are cacheable, CORS is open for `GET`, and each client address is
rate limited (`429` with `Retry-After`).

## Tests

Offline: nothing touches Codeforces, Supabase or an LLM.

```bash
venv/bin/python -m unittest discover -s tests
node --test tests/*.test.ts
```

## Contributing

Pull requests, bug reports and ideas are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). Good first projects: a browser
extension that shows the hints on codeforces.com, more model providers, and a larger evaluation of how often the hints are right.

## License and credit

Free to use, copy, modify and build on, including commercially, under the [Apache License 2.0](LICENSE). The one thing it asks
in return is credit: if you copy or redistribute this project or a work based on it, you must keep the copyright notice and the
[NOTICE](NOTICE) file, which names the author, and say what you changed.

Created by Ahmad Z. Shatnawi, known online as Leeking ([@ahmadsh2007](https://github.com/ahmadsh2007)).

## Support the project

Hinter is free to use and runs on free services, which is why it exists at all. Money would pay for better models (the hints are
only as good as the model that writes them), hosting and a domain, in that order; the plan and the numbers are in
[docs/funding.md](docs/funding.md). Sponsor links will be added here and on the repository's Sponsor button.
