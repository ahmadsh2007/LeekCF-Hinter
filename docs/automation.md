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

## Where to run it

Codeforces sits behind Cloudflare, which tends to accept home connections and may refuse the IP addresses of cloud
providers. So the first choice is the one that costs nothing and comes from your own network.

### 1. On your Mac (free, most likely to work)

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
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>30</integer></dict>
</dict></plist>
```

Load it with `launchctl load ~/Library/LaunchAgents/org.leekcf.hinter.plist`. The Mac has to be on (a job that was due
while it slept runs on wake). Read `~/leekcf-env/daily.log` to see what happened.

### 2. GitHub Actions (free, runs while your Mac is off)

`.github/workflows/daily-pipeline.yml` runs the same script on GitHub's servers every day. It does nothing until you
enable it. In the repository's **Settings → Secrets and variables → Actions** create:

- secrets: `SUPABASE_DATABASE_URL`, `SUPABASE_DATABASE_SECRET_KEY`, and the key of your model provider
  (`GEMINI_API_KEY` or `ANTHROPIC_API_KEY`);
- variables: `LLM_PROVIDER` (`gemini` or `anthropic`), the matching `GEMINI_MODEL` / `ANTHROPIC_MODEL`, and finally
  `PIPELINE_ENABLED` = `true`.

Start it once by hand from the **Actions** tab and read the log before trusting the schedule. If Codeforces answers
with 403 from GitHub's servers (the scraper stops after five in a row and says so), use option 1 instead.
GitHub also switches schedules off in repositories with no activity for 60 days.

### 3. Google Cloud (costs money)

`deploy/README.md` describes Cloud Run jobs and Cloud Scheduler. It needs a billing account.

## The public API is separate

The pipeline only fills the database. The public API (`src/api/`) reads it, and the `public_hints` view decides
what may be shown, so it is safe to run the API anywhere (see the README and `deploy/README.md`).
