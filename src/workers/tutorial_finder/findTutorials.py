import argparse
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from src.services.scraper.errors import ScrapingValidationError, TransientScrapeError
from src.utils.retry import retryOnNetworkErrors
from src.utils.supabasePaging import fetchAllRows
from src.workers.contest_monitor.contestProtector import parseTimestamp
from src.workers.tutorial_finder.tutorialSource import CodeforcesTutorialSource, TutorialPost

WAITING_STATUS = "WAITING_FOR_TUTORIAL"
FOUND_STATUS = "TUTORIAL_FOUND"
DEFAULT_CONTEST_LIMIT = 50
DEFAULT_DELAY_SECONDS = 2.0
# Several blocked/failed requests in a row mean we are being blocked: stop instead of hammering the site.
MAX_CONSECUTIVE_TRANSIENT_FAILURES = 5
DUPLICATE_FETCH_CHUNK_SIZE = 100  # canonical ids travel in the URL of an in_(...) filter
SAVE_CHUNK_SIZE = 50              # tutorial rows carry whole texts, so keep write requests small
# A contest that was checked and had no tutorial is not asked about again for this long. Without it every run would
# re-check the same stuck contests (pointless requests to Codeforces) and they would crowd out all the others.
NO_TUTORIAL_NOTE = "No tutorial found yet"
DEFAULT_RECHECK_AFTER_HOURS = 24.0

@dataclass
class WaitingProblem:
    id: str
    contestId: int
    keys: list[str]        # ids it may be written under in a post: its own first, then its duplicates' (e.g. Div. 2 twin)
    contestIds: set[int]   # contests whose page may link the post: its own and its duplicates'

class FailureStreak:
    def __init__(self):
        self.consecutive = 0
        self.total = 0

    def succeeded(self):
        self.consecutive = 0

    def failed(self):
        self.consecutive += 1
        self.total += 1

    @property
    def tripped(self) -> bool:
        return self.consecutive >= MAX_CONSECUTIVE_TRANSIENT_FAILURES

def loadWaitingProblems(client, now: datetime, recheckAfterHours: float) -> tuple[list[WaitingProblem], int]:
    """The problems to look for, and how many were left out because they were checked recently."""
    rows = fetchAllRows(client, "problems", "id, contest_id, last_error, updated_at", "id", equals={"stage_status": WAITING_STATUS})
    recheckAfter = timedelta(hours=recheckAfterHours)

    def checkedRecently(row: dict) -> bool:
        return row["last_error"] == NO_TUTORIAL_NOTE and now - parseTimestamp(row["updated_at"]) < recheckAfter

    skipped = sum(1 for row in rows if checkedRecently(row))
    problems = {
        row["id"]: WaitingProblem(row["id"], row["contest_id"], [row["id"]], {row["contest_id"]})
        for row in rows if not checkedRecently(row)
    }

    ids = list(problems)
    for start in range(0, len(ids), DUPLICATE_FETCH_CHUNK_SIZE):
        duplicates = (
            client.table("problems")
            .select("id, contest_id, canonical_problem_id")
            .eq("stage_status", "DUPLICATE")
            .in_("canonical_problem_id", ids[start:start + DUPLICATE_FETCH_CHUNK_SIZE])
            .execute()
            .data
        )
        for duplicate in sorted(duplicates, key=lambda row: row["id"]):
            canonical = problems[duplicate["canonical_problem_id"]]
            canonical.keys.append(duplicate["id"])
            canonical.contestIds.add(duplicate["contest_id"])
    return list(problems.values()), skipped

def saveTutorials(client, tutorials: dict[str, tuple[str, str, int]]) -> None:
    """tutorials: problem id -> (text, source url, contest id). The tutorial is stored first, the status last."""
    rows = [
        {"problem_id": problemId, "contest_id": contestId, "source_url": url, "raw_content": text,
         "author": None, "scraped_at": "now()"}
        for problemId, (text, url, contestId) in tutorials.items()
    ]
    for start in range(0, len(rows), SAVE_CHUNK_SIZE):
        client.table("tutorials").upsert(rows[start:start + SAVE_CHUNK_SIZE], on_conflict="problem_id").execute()

    ids = list(tutorials)
    for start in range(0, len(ids), SAVE_CHUNK_SIZE):
        (
            client.table("problems")
            .update({"stage_status": FOUND_STATUS, "last_error": None, "updated_at": "now()"})
            .in_("id", ids[start:start + SAVE_CHUNK_SIZE])
            .eq("stage_status", WAITING_STATUS)
            .execute()
        )

def markChecked(client, problemIds: list[str], sleep) -> None:
    """Remember that these problems were just looked for: they are skipped until the recheck wait has passed."""
    for start in range(0, len(problemIds), SAVE_CHUNK_SIZE):
        chunk = problemIds[start:start + SAVE_CHUNK_SIZE]
        try:
            retryOnNetworkErrors(lambda: (
                client.table("problems")
                .update({"last_error": NO_TUTORIAL_NOTE, "updated_at": "now()"})
                .in_("id", chunk)
                .eq("stage_status", WAITING_STATUS)
                .execute()
            ), sleep=sleep)
        except httpx.TransportError as e:
            print(f"Could not note the checked problems (database unreachable); they will just be checked again: {e}")

def run(client, source, contestLimit: int = DEFAULT_CONTEST_LIMIT, sleep=time.sleep, now: datetime | None = None,
        recheckAfterHours: float = DEFAULT_RECHECK_AFTER_HOURS) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    waiting, skipped = retryOnNetworkErrors(lambda: loadWaitingProblems(client, now, recheckAfterHours), sleep=sleep)
    counts = {"found": 0, "no_tutorial_yet": 0, "not_found": 0, "transient_failures": 0, "skipped_recently_checked": skipped}
    streak = FailureStreak()
    settled: set[str] = set()
    posts: dict[str, TutorialPost | None] = {}

    def loadPost(url: str) -> TutorialPost | None:
        if url not in posts:
            try:
                posts[url] = source.fetchPost(url)
                streak.succeeded()
            except ScrapingValidationError:
                posts[url] = None
                counts["not_found"] += 1
                streak.succeeded()
            except TransientScrapeError as e:
                print(f"[RETRY LATER] {url}: {e}")
                streak.failed()
                return None  # not cached: a later contest page may link it again
        return posts[url]

    def textFor(problem: WaitingProblem, post: TutorialPost) -> str | None:
        for key in problem.keys:
            if key in post.dynamic:
                try:
                    text = source.fetchDynamicTutorial(post, post.dynamic[key])
                    streak.succeeded()
                except TransientScrapeError as e:
                    print(f"[RETRY LATER] tutorial of {key}: {e}")
                    streak.failed()
                    text = None
                if text:
                    return text
                if streak.tripped:
                    return None
            if key in post.sections:
                return post.sections[key]
        return None

    contestIds = sorted({contestId for problem in waiting for contestId in problem.contestIds}, reverse=True)[:contestLimit]
    for contestId in contestIds:
        if streak.tripped:
            break
        if not any(contestId in problem.contestIds and problem.id not in settled for problem in waiting):
            continue

        failuresBefore = streak.total
        try:
            links = source.contestTutorialLinks(contestId)
            streak.succeeded()
        except ScrapingValidationError:
            print(f"Contest {contestId}: page not found.")
            counts["not_found"] += 1
            streak.succeeded()
            continue
        except TransientScrapeError as e:
            print(f"[RETRY LATER] contest {contestId}: {e}")
            streak.failed()
            continue

        def stillLookingFor(saved: dict) -> list[str]:
            return [problem.id for problem in waiting
                    if contestId in problem.contestIds and problem.id not in settled and problem.id not in saved]

        if not links:
            print(f"Contest {contestId}: no tutorial linked yet.")
            counts["no_tutorial_yet"] += 1
            markChecked(client, stillLookingFor({}), sleep)
            continue

        saved: dict[str, tuple[str, str, int]] = {}
        for url in links:
            if streak.tripped or all(problem.id in settled or problem.id in saved for problem in waiting):
                break
            post = loadPost(url)
            if post is None:
                continue
            # A post may cover other waiting problems too (Div. 1 and Div. 2 share one), so match them all.
            for problem in waiting:
                if problem.id in settled or problem.id in saved:
                    continue
                text = textFor(problem, post)
                if text:
                    saved[problem.id] = (text, url, problem.contestId)
                    print(f"Found the tutorial of {problem.id} in {url}")

        if saved:
            try:
                retryOnNetworkErrors(lambda: saveTutorials(client, saved), sleep=sleep)
            except httpx.TransportError as e:
                # Nothing is lost: the status only moves after the tutorial is stored, so the next run finds it again.
                print(f"[RETRY LATER] contest {contestId}: could not save to the database: {e}")
                streak.failed()
                continue
            settled.update(saved)
            counts["found"] += len(saved)

        # Only a contest that was looked at without any failure counts as checked.
        if streak.total == failuresBefore:
            markChecked(client, stillLookingFor({}), sleep)

    counts["transient_failures"] = streak.total
    if streak.tripped:
        print(f"Stopping: {streak.consecutive} transient failures in a row. "
              "Codeforces is probably blocking or rate limiting us; wait before running again.")
    print(f"Done. Tutorials found: {counts['found']}, contests with no tutorial yet: {counts['no_tutorial_yet']}, "
          f"not found: {counts['not_found']}, transient failures: {counts['transient_failures']}, "
          f"skipped (checked within {recheckAfterHours:g} h): {counts['skipped_recently_checked']}.")
    return counts

def main():
    parser = argparse.ArgumentParser(description="Find the official tutorials of problems in WAITING_FOR_TUTORIAL.")
    parser.add_argument("--limit", type=int, default=DEFAULT_CONTEST_LIMIT,
                        help=f"Maximum contests to look at this run, newest first (default {DEFAULT_CONTEST_LIMIT}).")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS,
                        help=f"Seconds to wait between requests (default {DEFAULT_DELAY_SECONDS}).")
    parser.add_argument("--recheck-hours", type=float, default=DEFAULT_RECHECK_AFTER_HOURS,
                        help=f"Do not look again for a tutorial that was not there this many hours ago (default {DEFAULT_RECHECK_AFTER_HOURS:g}; 0 = always look).")
    args = parser.parse_args()

    # Imported here so the module can be imported (e.g. by tests) without database credentials.
    from src.core.database.dbClient import supabase
    run(supabase, CodeforcesTutorialSource(delaySeconds=args.delay), args.limit, recheckAfterHours=args.recheck_hours)

if __name__ == "__main__":
    main()
