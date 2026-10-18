#!/bin/sh
# One pass over every stage, in dependency order. Run it after the sync job (hints-sync) has finished.
# A stage that stops early (e.g. Codeforces is blocking us) exits normally and the next stage just has less to do;
# a stage that crashes fails the whole job, so the failure is visible.
set -eu

SCRAPE_LIMIT="${SCRAPE_LIMIT:-1000}"
TUTORIAL_CONTEST_LIMIT="${TUTORIAL_CONTEST_LIMIT:-50}"
HINT_LIMIT="${HINT_LIMIT:-20}"
# Off by default: it makes the model write hints for problems that have no tutorial, which costs money
# and is less reliable. Turn it on (INCLUDE_WITHOUT_TUTORIAL=true) once the pilot hints look good.
INCLUDE_WITHOUT_TUTORIAL="${INCLUDE_WITHOUT_TUTORIAL:-false}"

echo "== 1/5 scrape statements =="
python -u -m src.services.scraper.mainChecker --limit "$SCRAPE_LIMIT" --delay 2

echo "== 2/5 link duplicates (Div. 1 A = Div. 2 C) =="
python -u -m src.workers.dedup.dedupProblems --apply

echo "== 3/5 contest protector =="
python -u -m src.workers.contest_monitor.contestProtector

echo "== 4/5 find tutorials =="
python -u -m src.workers.tutorial_finder.findTutorials --limit "$TUTORIAL_CONTEST_LIMIT" --delay 2

echo "== 5/5 generate hints =="
if [ "$INCLUDE_WITHOUT_TUTORIAL" = "true" ]; then
  python -u -m src.workers.hint_generator.generateHints --limit "$HINT_LIMIT" --include-without-tutorial
else
  python -u -m src.workers.hint_generator.generateHints --limit "$HINT_LIMIT"
fi
