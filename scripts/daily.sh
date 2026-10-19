#!/bin/bash
# The whole automatic flow, one pass: find new contests and problems on Codeforces, scrape them, link duplicates,
# wait for contests to be over, find tutorials, generate hints. Safe to run every day (and to re-run after an
# interruption): each stage only picks up what is still waiting. Run it from anywhere:
#
#   ENV_FILE=~/leekcf-env/staging.env scripts/daily.sh
#
# Knobs (environment): PYTHON (default venv/bin/python), SCRAPE_LIMIT, TUTORIAL_CONTEST_LIMIT, HINT_LIMIT,
# INCLUDE_WITHOUT_TUTORIAL, PIPELINE_SKIP_SYNC=1 (skip the Node sync), PIPELINE_DRY_RUN=1 (print the commands only).
set -euo pipefail
cd "$(dirname "$0")/.."

export PYTHON="${PYTHON:-venv/bin/python}"

if [ "${PIPELINE_SKIP_SYNC:-}" != "1" ]; then
  echo "--- sync contests and new problems from the Codeforces API ---"
  echo "== node src/core/database/insertProblem.ts =="
  if [ "${PIPELINE_DRY_RUN:-}" != "1" ]; then node src/core/database/insertProblem.ts; fi
fi

exec bash deploy/run-pipeline.sh
