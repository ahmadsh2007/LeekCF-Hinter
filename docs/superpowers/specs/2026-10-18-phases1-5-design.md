# Phases 1-5: contest protector, tutorial finder, hint generator, public API, deploy

Date: 2026-10-18. Branch `hints_pipeline` (cut from `testing_env`).
Status: written after "just finish the whole project"; the roadmap and API option B (a thin read-only API in
front of a gated database view) were proposed in chat. Every decision below can be vetoed.

## What the design rests on (checked against real Codeforces pages)

- Python `requests` with a browser User-Agent passes Cloudflare for problem pages, contest pages and blog
  entries. `curl` was refused (403, "Just a moment..."), and a plain `requests` call to one contest page got the
  same 403 once, so a 403 stays a *transient* failure everywhere.
- A contest page has a "Contest materials" box whose links include `Tutorial`, `Tutorial (en)` pointing to a
  blog entry. Div. 1 and Div. 2 of one round usually link the same entry.
- Editorials come in two shapes:
  1. **Static**: all text is in the blog post, split into `spoiler` blocks (Hint 1, Solution, Code, ...).
  2. **Dynamic**: `<div class="problemTutorial" problemcode="1800A">Tutorial is loading...</div>`. Codeforces' own
     script fills it with a `POST /data/problemTutorial` (form field `problemCode`, `X-Csrf-Token` header from the
     page's `<meta>`, session cookies) that answers `{"success","public","html"}`. 3 of the 5 editorials sampled
     used this.
- Each problem's section in a post starts with an anchor to `/contest/{contestId}/problem/{index}`, even in a post
  that covers two contests.
- Old problems render math as HTML spans, which the Phase 0 parser mangled; that was fixed first (`htmlText.py`).

## Pipeline

```
SCRAPED_WAITING_FOR_CONTEST --protector--> WAITING_FOR_TUTORIAL --finder--> TUTORIAL_FOUND --generator--> HINTS_GENERATED
```

`DUPLICATE` problems never move; the canonical problem carries the tutorial and the hints, and the duplicate
resolves to it when read.

**No-tutorial policy.** The original ask was "tutorial, if any exists". The generator only takes `TUTORIAL_FOUND`
problems by default. With `--include-without-tutorial` it also takes `WAITING_FOR_TUTORIAL` problems whose
contest ended at least `--no-tutorial-after-days` (default 7) ago and writes `grounded_in_tutorial = false`.
It is off by default so a backlog is never generated before the finder has been through it.

## Migrations (additive, applied by hand like 001)

- `003_pipeline_state.sql`: `problems.hint_attempts smallint not null default 0` (generation failures; scraping
  keeps `scrape_attempts`), and `UNIQUE (problem_id)` on `tutorials` so the finder can upsert (one official tutorial
  per canonical problem).
- `004_public_hints_view.sql`: the view `public.public_hints` and its grants (below).

No RLS statements: RLS is already on for every table.

## Phase 1: contest protector (`src/workers/contest_monitor/`)

Moves `SCRAPED_WAITING_FOR_CONTEST` -> `WAITING_FOR_TUTORIAL` for problems whose contest is over:
`phase = 'FINISHED'` **and** `now >= start_time + duration + 2 hours` (the blueprint's margin). Both conditions are
needed: the stored phase can only be stale in the safe direction (a finished contest still showing `CODING`
just waits), and the clock rule guards against a phase flag set early. Pure planner (`isContestOver`,
`planPromotions`) plus a thin DB runner with the same shape as the dedup worker. Run the contest sync
(`insertContest.ts`) first so phases are fresh.

## Phase 3: tutorial finder (`src/workers/tutorial_finder/`)

(Built before the generator because the generator consumes its output.)

1. Group `WAITING_FOR_TUTORIAL` problems by contest; map every duplicate to its canonical, and also scan the
   duplicates' contests (Div. 1 / Div. 2 may have separate posts).
2. Per contest: fetch the contest page, collect `Tutorial` / `Editorial` links from "Contest materials" (English
   first). No link yet -> leave the problems waiting; they are checked again next run.
3. Per post: **static** sections are cut at problem anchors (a block that *starts* with an anchor to
   `/contest/{c}/problem/{i}` opens that problem's section; the next such block closes it). Anchors in the middle of
   a sentence are references, not section starts. **Dynamic** placeholders are fetched one by one through the
   data endpoint (skipped when `public` is not `"true"`). A problem keeps a dynamic result over a static one.
4. Section text goes through the same `extractText` as statements, except `<pre>` code blocks are dropped
   (hints need the idea, not the code, and code costs tokens). Spoiler blocks become `Title:` + body.
5. A section shorter than 80 characters after cleaning (e.g. "authored by X") is not a tutorial.
6. Upsert `tutorials` (problem_id, contest_id, source_url, raw_content, author), then set `TUTORIAL_FOUND`
   (status last). Network/blocks are transient (retry next run); a missing page is a clean "not found".

`author` is stored as NULL: posts credit authors in free text and guessing would put wrong names in the table.

## Phase 2: hint generator (`src/services/llm/`, `src/workers/hint_generator/`)

- Provider: Gemini through the AI Studio REST API with plain `requests` (no new dependency), behind a small
  `generate(system, user) -> str` interface so Vertex AI can replace it. Configured by `GEMINI_API_KEY` and
  `GEMINI_MODEL`; **there is no default model** so a wrong name fails loudly instead of silently picking one.
- Prompt (versioned, `PROMPT_VERSION`): five levels as in the blueprint (1 observation, 2 key idea, 3 algorithm,
  4 edge cases and complexity, 5 full walkthrough in prose), Markdown with `$...$` math, no code, and the
  explicit rule that levels 1-2 name no algorithm or data structure. Input: statement, input/output/interaction
  sections, limits, samples, notes, and the editorial text if there is one. JSON output through
  `responseSchema`.
- Validation (`hintValidator.py`, pure): exactly levels 1-5 once each, non-empty, bounded length, and levels 1-2
  free of a fixed list of algorithm / data-structure names (word-boundary match). A violation is retried twice
  with the violation quoted back to the model; after that `hint_attempts` goes up and `last_error` says why;
  at 5 attempts the problem becomes `FAILED`. This is a heuristic gate, not a proof; the pilot run is how
  quality is judged.
- Writes the five hints in **one** upsert (all or nothing), then sets `HINTS_GENERATED` last. Never called on a
  user request.
- `--dry-run` prints the hints and writes nothing; `--limit` (default 20) bounds cost.

## Phase 4: public API (`src/api/`, option B)

Read-only HTTP service on Cloud Run, zero new dependencies (`node:http`, `@supabase/supabase-js` is already in
`package.json`).

```
GET /v1/problems/{contestId}/{index}/hints
200 {"problem":{"id","contestId","index","name","rating","tags"},
     "hints":[{"level":1,"content":"..."}, ...],
     "groundedInTutorial":true,"generatedAt":"..."}
404 {"error":{"code":"not_found",...}}   400 invalid id   429 rate limited   405/404 otherwise
GET /v1/health
```

- It serves hints and basic metadata only; never statements or editorials (Codeforces' content).
- **The spoiler gate is the database.** The view `public_hints` returns a row only when the contest of the
  requested problem *and* of the problem that holds the hints are `FINISHED` and over by 2 hours, and the hint
  holder is `HINTS_GENERATED`. A duplicate resolves to its canonical's hints inside the view. A bug in API code
  cannot leak a live contest's hints, because the API cannot read anything else.
- **Least privilege.** The API holds the *publishable* (anon) key, not the secret key. `anon` is granted `SELECT` on the view only (explicit
  `REVOKE ALL` first, because Supabase's default privileges grant everything); the base tables have RLS with no
  policy, and the view runs with its owner's rights, so it is the single readable door.
- Rate limit: per-IP token bucket in memory (per instance; `--max-instances` bounds the total). Client IP is the
  right-most `X-Forwarded-For` entry (the one Cloud Run appends). Cache: in-memory TTL cache plus
  `Cache-Control: public, max-age=300, s-maxage=3600`. CORS `*` for GET. Only GET/HEAD/OPTIONS.
- Input: `contestId` digits only, `index` `^[A-Za-z][0-9]{0,2}$` upper-cased; anything else is 400 before any
  database call.

## Phase 5: deploy (`deploy/`, `Dockerfile.*`)

Two images: the API (`node:24-slim`) and the workers (`python:3.14-slim`); a Node job for the contest/problem
sync. A shell script chains the worker stages in order; Cloud Scheduler triggers them daily. These files are
**written but not built or deployed** by me (no Docker or gcloud here); `deploy/README.md` lists the commands
and what to check after the first run.

## Out of scope

Browser extension; Vertex AI client (the interface allows it); translating hints; user accounts or API keys for
the public API (add if abuse appears); a backfill of the 11k historic problems (an operator decision: run the
stages in order and watch cost).

## Verification status (what was and was not proven)

**Proven here**
- 262 Python and 41 Node tests, all offline. The safety rules were mutation-tested: sabotaging each one (the 2-hour
  rule, the contest re-check in the generator, the status guards, write order, the circuit breakers, the key-safety
  check, the right-most client address, the rate limit, the view's two contest gates) makes a test fail.
- Migrations 003 and 004 on a real Postgres 16 with Supabase-like roles, default grants and RLS: as `anon`, the view
  returns only the gated rows, the base tables return nothing, and writes through the view fail. All five migrations
  also apply as a single script on an empty database.
- The statement extractor, the tutorial parser and the tutorial finder against live Codeforces pages: 4 problem pages,
  6 contest pages, 5 editorials (static and dynamic formats), and the Div. 1 / Div. 2 duplicate pair, using a fake
  database so nothing was written anywhere.
- The API server boots, refuses a secret key, and answers health, 400 and 405; the sync script runs from exactly the
  files its Dockerfile copies.

**Not proven**
- Anything against a real Supabase project: the migrations in the dashboard's SQL editor, real PostgREST answers,
  and the `anon` key's behaviour through Supabase's gateway. `docs/staging-runbook.md` has the checks.
- Gemini: the request and response shapes follow the documented REST API but were never sent, so a wrong model id,
  a schema the model rejects, or poor hint quality only shows up on the first `--dry-run`.
- The Docker images and every `gcloud` command in `deploy/README.md`.
- Cloud Run adding the client address as the *right-most* `X-Forwarded-For` entry (the rate limiter relies on it).
- Statement fidelity beyond the pages checked; spot-check about ten stored statements after the first scrape.
