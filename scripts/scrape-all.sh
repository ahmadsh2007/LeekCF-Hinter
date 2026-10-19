#!/bin/bash
# Scrapes every problem that is still waiting (DISCOVERED), 1000 at a time, until none is left. It is the one-off
# backfill for a freshly loaded database (about 3.75 seconds per problem, so 10,000 problems take roughly 10 hours).
# Safe to stop (Ctrl+C) and to start again: finished problems are never scraped twice.
#
#   ENV_FILE=~/leekcf-env/staging.env scripts/scrape-all.sh
#
# It stops by itself if a batch scrapes nothing, which means Codeforces is blocking us: wait, then start it again.
# Keep the Mac awake with:  caffeinate -i scripts/scrape-all.sh
set -uo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-venv/bin/python}"
batch=0
while true; do
  batch=$((batch + 1))
  echo "=== batch $batch started $(date '+%H:%M:%S') ==="
  output=$(mktemp)
  "$PYTHON" -u -m src.services.scraper.mainChecker --limit 1000 --delay 2 2>&1 | tee "$output"
  status=${PIPESTATUS[0]}
  summary=$(grep -E "^(Done\. Scraped|No problems found)" "$output" | tail -1)
  rm -f "$output"
  echo "=== batch $batch finished: ${summary:-no summary line} ==="

  if [ "$status" -ne 0 ]; then echo "STOPPED: the scraper exited with $status"; exit "$status"; fi
  case "$summary" in
    "No problems found"*) echo "ALL DONE"; exit 0;;
    *"Scraped: 0,"*) echo "STOPPED: a batch scraped nothing (probably blocked by Codeforces). Wait, then run it again."; exit 0;;
  esac
done
