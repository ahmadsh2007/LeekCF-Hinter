# Trying everything on a throwaway Supabase project

Use a second, empty Supabase project (for example "LeekCF Hinter Temp"). Nothing here touches production, and nothing
needs a backup because the project can be wiped and rebuilt from the migrations at any time.

Keep its keys in a file **outside** the repository, e.g. `~/leekcf-env/staging.env`:

```
SUPABASE_DATABASE_URL=https://YOUR-PROJECT-REF.supabase.co
SUPABASE_DATABASE_SECRET_KEY=sb_secret_...
SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
ANTHROPIC_API_KEY=sk-ant-...
```

(Claude Opus 5.5 at high effort is the default; add `ANTHROPIC_MODEL=` / `ANTHROPIC_EFFORT=` to change that.)

Every command below starts with `ENV_FILE=~/leekcf-env/staging.env`, which points the script at that project instead of
`config/.env`. Each script prints `Supabase target: <host>` first so you can see where it is about to write.

## 1. Build the database (you, about 2 minutes)

1. In Terminal, from the repository folder: `cat migrations/00*.sql | pbcopy` (copies all five migrations). If the project already has 000-002, copy only the new ones: `cat migrations/003*.sql migrations/004*.sql | pbcopy`.
2. Supabase dashboard -> the Temp project -> **SQL Editor** -> **New query** -> paste -> **Run**.
   Expect "Success. No rows returned". If you get a red error, copy it to me.
3. Turn on row level security, like production already has (new query -> paste -> Run):

   ```sql
   do $$ declare t record; begin
     for t in select tablename from pg_tables where schemaname = 'public' loop
       execute format('alter table public.%I enable row level security', t.tablename);
     end loop;
   end $$;
   ```

That is the only part that needs you in the dashboard. Once the keys file has the URL, everything below can be run by
you or by me.

## 2. Load problems and keep a small sample

```bash
ENV_FILE=~/leekcf-env/staging.env node src/core/database/insertProblem.ts
```

This loads about 1,900 contests and 11,000 problems. Park everything except a small sample (3 Div. 1 / Div. 2 pairs,
4 interactive problems, 4 others) so the live checks below stay short. Run in the SQL editor:

```sql
with pairs as (
  select p.name, c.start_time from problems p join contests c on c.id = p.contest_id
  group by 1, 2 having count(*) > 1 limit 3
), keep as (
  select p.id from problems p join contests c on c.id = p.contest_id
    join pairs on pairs.name = p.name and pairs.start_time = c.start_time
  union (select id from problems where tags @> '{interactive}' order by id limit 4)
  union (select id from problems order by id limit 4)
)
update problems set stage_status = 'FAILED' where id not in (select id from keep);
```

## 3. Walk the pipeline, one stage at a time

```bash
E=~/leekcf-env/staging.env
ENV_FILE=$E venv/bin/python -u -m src.services.scraper.mainChecker --delay 2
ENV_FILE=$E venv/bin/python -u -m src.workers.dedup.dedupProblems --report ~/leekcf-env/dedup_review.csv   # dry run
ENV_FILE=$E venv/bin/python -u -m src.workers.dedup.dedupProblems --apply
ENV_FILE=$E venv/bin/python -u -m src.workers.contest_monitor.contestProtector
ENV_FILE=$E venv/bin/python -u -m src.workers.tutorial_finder.findTutorials --limit 20
ENV_FILE=$E venv/bin/python -u -m src.workers.hint_generator.generateHints --dry-run --limit 5
```

What to look at after each:

| After | Check (SQL editor) | Good looks like |
|---|---|---|
| scrape | `select stage_status, count(*) from problems group by 1;` | the sample is `SCRAPED_WAITING_FOR_CONTEST`; any `FAILED` row has a `last_error` |
| scrape | `select problem_id, interaction_specification is not null as interactive, left(statement_text, 150) from problem_specifications;` | interactive problems say `true`; math appears as `$$$...$$$` and paragraphs read normally |
| dedup | `select id, canonical_problem_id from problems where stage_status = 'DUPLICATE';` | each Div. 2 twin points at its Div. 1 problem; the CSV lists pairs whose text differs |
| protector | the same status count | old contests moved to `WAITING_FOR_TUTORIAL` |
| tutorials | `select problem_id, length(raw_content) from tutorials;` | rows for problems whose contest has a tutorial; those problems are `TUTORIAL_FOUND` |
| hints (dry run) | read the printed hints | 2 to 5 hints (more for harder problems); the early hints name no algorithm; the last hint is a correct full walkthrough. Read them against the real editorial. The run ends with a `Usage:` line: tokens and dollars spent. |

Re-run `insertProblem.ts` once more and recount the statuses: **they must not change** (the sync no longer resets
pipeline state).

To scrape again from scratch: `update problems set stage_status = 'DISCOVERED', scrape_attempts = 0, last_error = null where stage_status in ('SCRAPED_WAITING_FOR_CONTEST', 'FAILED');`

## 4. Write real hints, then check the public side

Only after the dry-run hints look right:

```bash
ENV_FILE=$E venv/bin/python -u -m src.workers.hint_generator.generateHints --limit 5
```

Multiply the `Usage:` cost per problem by the number of problems to replace the guesses in `docs/cost-estimate.md`.

Then run the API against the project with the **publishable** key and ask it for a problem that has hints:

```bash
set -a; . ~/leekcf-env/staging.env; set +a
node src/api/server.ts &
curl -s localhost:8080/v1/problems/CONTEST_ID/INDEX/hints
```

And prove the database really is closed to the public key (all three must show `[]` or an error, never data):

```bash
for table in hints problems problem_specifications tutorials; do
  curl -s "$SUPABASE_DATABASE_URL/rest/v1/$table?select=*&limit=1" -H "apikey: $SUPABASE_PUBLISHABLE_KEY"; echo
done
curl -s "$SUPABASE_DATABASE_URL/rest/v1/public_hints?select=problem_id,hint_level&limit=3" -H "apikey: $SUPABASE_PUBLISHABLE_KEY"
```

The last one is the only door: it returns rows only for problems whose contest ended more than 2 hours ago.

## Production

Production is the same steps with `config/.env`, after the dashboard has its migrations. If production holds nothing
you want to keep, the simplest path is: SQL editor, run `migrations/001...` to `004...` in order (they are written to
fail loudly and roll back rather than half-apply), then the same stages. `002` drops two obsolete tables.
