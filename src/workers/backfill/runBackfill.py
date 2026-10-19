import argparse
import sys
import time
import traceback
from collections import Counter
from dataclasses import dataclass
from typing import Callable
from src.services.llm.errors import LlmRequestError
from src.utils.supabasePaging import fetchAllRows
from src.workers.hint_generator.generateHints import MAX_CONSECUTIVE_TRANSIENT_FAILURES

# A generator pass that ended on this many provider errors in a row hit the daily or per-minute quota: wait it out.
QUOTA_ERRORS_IN_A_ROW = MAX_CONSECUTIVE_TRANSIENT_FAILURES
DEFAULT_IDLE_SECONDS = 600
DEFAULT_QUOTA_PAUSE_SECONDS = 1800
MAX_CONSECUTIVE_CRASHES = 3

@dataclass
class Stages:
    protector: Callable[[], dict]
    finder: Callable[[], dict]
    generator: Callable[[bool], dict]  # takes includeWithoutTutorial

def statusCounts(client) -> dict[str, int]:
    return dict(Counter(row["stage_status"] for row in fetchAllRows(client, "problems", "stage_status", "id")))

def runBackfill(client, stages: Stages, sleep=time.sleep, log=print, idleSeconds: float = DEFAULT_IDLE_SECONDS,
                quotaPauseSeconds: float = DEFAULT_QUOTA_PAUSE_SECONDS, maxPasses: int | None = None) -> None:
    """
    Repeats protector -> tutorial finder -> hint generator until the whole list is done. It is meant to run for days next
    to the scraper: it waits while there is nothing to do, waits out rate limits, and switches on hints for problems
    without a tutorial only once scraping is over and the finder has nothing left to check. It stops by itself.
    """
    passes = 0
    crashes = 0
    while True:
        passes += 1
        try:
            scrapingDone = statusCounts(client).get("DISCOVERED", 0) == 0
            promoted = stages.protector().get("promoted", 0)
            found = stages.finder()
            finderIdle = found.get("found", 0) == 0 and found.get("no_tutorial_yet", 0) == 0 and found.get("transient_failures", 0) == 0
            ungrounded = scrapingDone and finderIdle
            generated = stages.generator(ungrounded)
            crashes = 0
        except LlmRequestError:
            raise  # a bad key or closed billing: looping would only repeat it
        except Exception as e:
            crashes += 1
            log(f"[PASS {passes} CRASHED ({crashes}/{MAX_CONSECUTIVE_CRASHES})] {type(e).__name__}: {e}")
            traceback.print_exc()
            if crashes >= MAX_CONSECUTIVE_CRASHES:
                raise
            if maxPasses is not None and passes >= maxPasses:
                return
            sleep(idleSeconds)
            continue

        progress = promoted + found.get("found", 0) + generated.get("generated", 0) + generated.get("failed", 0)
        after = statusCounts(client)
        log(f"[PASS {passes}] promoted {promoted}, tutorials found {found.get('found', 0)}, hints generated "
            f"{generated.get('generated', 0)}; now: {dict(sorted(after.items()))}")

        nothingLeftToDo = ungrounded and progress == 0 and not any(
            after.get(status, 0) for status in ("DISCOVERED", "SCRAPED_WAITING_FOR_CONTEST", "TUTORIAL_FOUND"))
        if nothingLeftToDo:
            log("ALL DONE. Anything still waiting belongs to a contest that is too recent; the daily pipeline picks it up.")
            return
        if maxPasses is not None and passes >= maxPasses:
            return

        if generated.get("transient_failures", 0) >= QUOTA_ERRORS_IN_A_ROW:
            log(f"The model API is rate limiting or out of quota: waiting {quotaPauseSeconds / 60:g} minutes.")
            sleep(quotaPauseSeconds)
        elif progress == 0:
            log(f"Nothing to do right now (scraping or tutorials still catching up): waiting {idleSeconds / 60:g} minutes.")
            sleep(idleSeconds)

def main():
    parser = argparse.ArgumentParser(description="Run the pipeline stages repeatedly until every problem has its hints.")
    parser.add_argument("--tutorial-contests", type=int, default=40, help="Contests the tutorial finder looks at per pass.")
    parser.add_argument("--hints-per-pass", type=int, default=100, help="Problems the hint generator handles per pass.")
    parser.add_argument("--hint-delay", type=float, default=6.0, help="Seconds between model calls (free tiers limit requests per minute).")
    parser.add_argument("--finder-delay", type=float, default=2.0, help="Seconds between Codeforces requests.")
    parser.add_argument("--idle-minutes", type=float, default=DEFAULT_IDLE_SECONDS / 60)
    parser.add_argument("--quota-pause-minutes", type=float, default=DEFAULT_QUOTA_PAUSE_SECONDS / 60)
    args = parser.parse_args()

    # Imported here so the module can be imported (e.g. by tests) without credentials.
    from src.core.database.dbClient import supabase
    from src.services.llm.llmProvider import createClientFromEnvironment
    from src.workers.contest_monitor import contestProtector
    from src.workers.hint_generator import generateHints
    from src.workers.tutorial_finder import findTutorials
    from src.workers.tutorial_finder.tutorialSource import CodeforcesTutorialSource

    llm = createClientFromEnvironment()
    source = CodeforcesTutorialSource(delaySeconds=args.finder_delay)
    stages = Stages(
        protector=lambda: contestProtector.run(supabase),
        finder=lambda: findTutorials.run(supabase, source, args.tutorial_contests),
        generator=lambda includeWithoutTutorial: generateHints.run(
            supabase, llm, limit=args.hints_per_pass, includeWithoutTutorial=includeWithoutTutorial, delaySeconds=args.hint_delay),
    )
    try:
        runBackfill(supabase, stages, idleSeconds=args.idle_minutes * 60, quotaPauseSeconds=args.quota_pause_minutes * 60)
    except LlmRequestError as e:
        print(f"Stopping: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
