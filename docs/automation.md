# Running the pipeline automatically

`scripts/daily.sh` is the whole automatic flow in one pass:

1. **sync** contests and problems from the Codeforces API (this is what detects new problems),
2. **scrape** the new problems' statements,
3. **link duplicates** (Div. 1 A = Div. 2 C),
4. **protect**: only problems whose contest ended at least 2 hours ago move on,
5. **find tutorials** for those problems,
6. **generate hints** (for problems with a tutorial; add `INCLUDE_WITHOUT_TUTORIAL=true` for the rest).

It is safe to run every day and to re-run after an interruption: every stage only picks up what is still waiting.
A crashing stage stops the run; a stage that is throttled or blocked just does less. Try it first without doing
anything: `PIPELINE_DRY_RUN=1 scripts/daily.sh` prints the commands.

Settings are environment variables (`SCRAPE_LIMIT`, `TUTORIAL_CONTEST_LIMIT`, `HINT_LIMIT`,
`INCLUDE_WITHOUT_TUTORIAL`, and the model settings in the README). Point it at a project with `ENV_FILE=...`.

## The one-off backlog

A freshly loaded database has thousands of problems to scrape and hint, far more than one daily pass. Use two restartable
scripts instead, side by side:

- `scripts/scrape-all.sh` scrapes every waiting problem, 1000 at a time (about 16 problems a minute), and stops by itself
  if Codeforces starts blocking.
- `scripts/backfill.sh` repeats the protector, the tutorial finder and the hint generator as problems arrive, waits out model
  rate limits, and finishes by itself. Hints for problems without a tutorial are switched on only once scraping is over and the
  finder has nothing left to check.

Both survive short database outages (502s, dropped connections) by retrying, and both can be stopped and started again at any
time because all progress is in the database. Afterwards `scripts/daily.sh` keeps up with new contests.

## Checking on it, and when something goes wrong

- **GitHub → Actions tab** lists every run. A red cross means a stage crashed; open the run and the log of the step
  "Run scripts/daily.sh": each stage prints a heading (`--- 1/6 scrape statements ---` … `--- 6/6 save the API usage statistics ---`),
  so the error sits right under the stage that failed. GitHub emails you about failed runs by default (check
  **github.com/settings/notifications → Actions**).
- **A green run is not proof that anything was produced**: a stage that Codeforces blocks, or a model with no quota left,
  stops quietly and the run goes on. So every run ends with a **Status report** step. Its report is on the run's page (under
  the job list) and shows the problems per stage, what the last 24 hours produced (new problems, hints per model), why the
  failed problems failed, and **warnings**. It turns the run red, and so produces the failure email, in two cases:
  hints are waiting but none was written for a day (quota, key or model trouble: read stage 5), or statements stay unscraped
  for more than two days (Codeforces refusing the connection: read stage 1).
- **Look at any time, from the Mac**: `ENV_FILE=~/leekcf-env/staging.env venv/bin/python -m src.workers.status.pipelineStatus`
- The three problems this cannot catch: GitHub switching the schedule off after 60 days without repository activity (the daily
  runs just stop appearing in the Actions tab; any push, or **Enable workflow** there, starts them again), the Worker itself
  being down (open `https://leekcf-hinter-api.leekcf.workers.dev/health`), and bad hints (the report counts hints, it cannot
  judge them).

## Where to run it

### 1. GitHub Actions (free, runs while your Mac is off): the plan

`.github/workflows/daily-pipeline.yml` runs `scripts/daily.sh` on GitHub's servers every day at **08:15 UTC**, right
after Google resets the free daily model quotas (midnight US Pacific is 07:00 UTC, or 08:00 UTC when the US clocks go
back). One run therefore spends the whole day's free quota: about 80 hints from the four 20-a-day flash models plus
about 500 from `gemini-3.5-flash-lite`. `HINT_LIMIT=600` keeps the run to about four hours, inside GitHub's six-hour cap.
`.github/workflows/usage-export.yml` saves the API's usage statistics (`docs/usage-stats.md`). Both are free for a public
repository.

One command creates every secret and setting, starts test runs and switches the schedules on, step by step:

```bash
ENV_FILE=~/leekcf-env/staging.env scripts/setup-github-automation.sh
```

By hand, in **Settings → Secrets and variables → Actions**:

- secrets: `SUPABASE_DATABASE_URL`, `SUPABASE_DATABASE_SECRET_KEY`, `GEMINI_API_KEY` (or `ANTHROPIC_API_KEY`), and for the
  usage statistics `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN`;
- variables: `LLM_PROVIDER` (`gemini`), `GEMINI_MODEL`, `GEMINI_THINKING_LEVEL`, `HINT_LIMIT`, `TUTORIAL_CONTEST_LIMIT`, and
  finally `PIPELINE_ENABLED` = `true` (and `USAGE_EXPORT_ENABLED` = `true` for the usage export).

**Not yet run on GitHub.** Start it once by hand from the **Actions** tab and read the log before trusting the schedule.
Codeforces sits behind Cloudflare, which tends to accept home connections and may refuse the addresses of cloud
providers: if the scraper or the tutorial finder reports 403 / "Codeforces is probably blocking" from GitHub's servers,
that part has to stay on option 2 (the other parts still work). GitHub also switches schedules off in repositories with
no activity for 60 days.

Both the Mac and GitHub use the same Gemini key, so they share one daily quota: stop the Mac's `scripts/backfill.sh` once
GitHub's runs work.

### 2. On your Mac (free, most likely to work with Codeforces)

Test once by hand: `ENV_FILE=~/leekcf-env/staging.env scripts/daily.sh`. Then run it every day with launchd. Save this as
`~/Library/LaunchAgents/org.leekcf.hinter.plist`, replacing `YOUR_USER`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>org.leekcf.hinter</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>-lc</string>
    <string>cd /Users/YOUR_USER/Desktop/LeekCF-Hinter &amp;&amp; ENV_FILE=$HOME/leekcf-env/staging.env /usr/bin/caffeinate -i scripts/daily.sh &gt;&gt; $HOME/leekcf-env/daily.log 2&gt;&amp;1</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>15</integer></dict>
</dict></plist>
```

Load it with `launchctl load ~/Library/LaunchAgents/org.leekcf.hinter.plist`. The Mac has to be on (a job that was due
while it slept runs on wake). Read `~/leekcf-env/daily.log` to see what happened.

### 3. Google Cloud (costs money)

`deploy/README.md` describes Cloud Run jobs and Cloud Scheduler. It needs a billing account.

## The public API is separate

The pipeline only fills the database. The public API (`src/api/`) reads it, and the `public_hints` view decides
what may be shown, so it is safe to run the API anywhere (see the README and `deploy/README.md`).
