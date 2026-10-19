#!/bin/sh
# One pass over every Python stage, in dependency order. Run it after the contest/problem sync has finished
# (scripts/daily.sh does both). A stage that stops early (e.g. Codeforces is blocking us) exits normally and the next
# stage just has less to do; a stage that crashes fails the whole run, so the failure is visible.
# PIPELINE_DRY_RUN=1 only prints the commands.
set -eu

PYTHON="${PYTHON:-python}"
SCRAPE_LIMIT="${SCRAPE_LIMIT:-1000}"
TUTORIAL_CONTEST_LIMIT="${TUTORIAL_CONTEST_LIMIT:-50}"
HINT_LIMIT="${HINT_LIMIT:-20}"
# Off by default: it makes the model write hints for problems that have no tutorial, which is less reliable.
# Turn it on (INCLUDE_WITHOUT_TUTORIAL=true) once the tutorial finder has been through the backlog.
INCLUDE_WITHOUT_TUTORIAL="${INCLUDE_WITHOUT_TUTORIAL:-false}"

run() {
  echo "== $* =="
  if [ "${PIPELINE_DRY_RUN:-}" = "1" ]; then return 0; fi
  "$@"
}

echo "--- 1/5 scrape statements ---"
run "$PYTHON" -u -m src.services.scraper.mainChecker --limit "$SCRAPE_LIMIT" --delay 2

echo "--- 2/5 link duplicates (Div. 1 A = Div. 2 C) ---"
run "$PYTHON" -u -m src.workers.dedup.dedupProblems --apply

echo "--- 3/5 contest protector ---"
run "$PYTHON" -u -m src.workers.contest_monitor.contestProtector

echo "--- 4/5 find tutorials ---"
run "$PYTHON" -u -m src.workers.tutorial_finder.findTutorials --limit "$TUTORIAL_CONTEST_LIMIT" --delay 2

echo "--- 5/5 generate hints ---"
if [ "$INCLUDE_WITHOUT_TUTORIAL" = "true" ]; then
  run "$PYTHON" -u -m src.workers.hint_generator.generateHints --limit "$HINT_LIMIT" --include-without-tutorial
else
  run "$PYTHON" -u -m src.workers.hint_generator.generateHints --limit "$HINT_LIMIT"
fi
