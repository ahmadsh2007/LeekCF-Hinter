#!/bin/bash
# Runs the whole backlog to the end, unattended: repeats protector -> tutorial finder -> hint generator, waits out rate
# limits, and stops by itself when every problem has its hints. Start the scraper next to it (scripts/scrape-all.sh);
# this one waits for new problems to appear. Safe to stop (Ctrl+C) and to start again.
#
#   ENV_FILE=~/leekcf-env/staging.env caffeinate -i scripts/backfill.sh
#
# Options are passed on, e.g. --hints-per-pass 50 --hint-delay 10 (see runBackfill.py --help).
set -uo pipefail
cd "$(dirname "$0")/.."
exec "${PYTHON:-venv/bin/python}" -u -m src.workers.backfill.runBackfill "$@"
