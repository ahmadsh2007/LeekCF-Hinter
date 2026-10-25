import argparse
import sys
import time
import httpx
from datetime import datetime, timedelta, timezone
from src.services.llm.errors import LlmBlockedError, LlmRequestError, LlmTruncatedError, TransientLlmError
from src.services.llm.llmProvider import createClientFromEnvironment
from src.services.llm.hintPrompt import (
    PROMPT_VERSION,
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    ProblemForHints,
    buildUserPrompt,
)
from src.utils.retry import retryOnNetworkErrors
from src.utils.supabasePaging import fetchAllRows
from src.workers.contest_monitor.contestProtector import fetchContests, isContestOver, parseTimestamp
from src.workers.hint_generator.hintValidator import Hint, HintValidationError, validateHints

WITH_TUTORIAL_STATUS = "TUTORIAL_FOUND"
WITHOUT_TUTORIAL_STATUS = "WAITING_FOR_TUTORIAL"
DONE_STATUS = "HINTS_GENERATED"
DEFAULT_LIMIT = 20
DEFAULT_DELAY_SECONDS = 2.0
DEFAULT_NO_TUTORIAL_AFTER_DAYS = 7
# A problem whose answers keep being rejected is given up on after this many runs of trying.
MAX_HINT_ATTEMPTS = 5
# Extra calls within one attempt, each told why the previous answer was rejected.
MAX_FORMAT_RETRIES = 2
# Several provider errors in a row mean rate limiting or an outage: stop instead of hammering it.
MAX_CONSECUTIVE_TRANSIENT_FAILURES = 5
MAX_ERROR_CHARS = 1000

class MissingDataError(Exception):
    """The database lacks something the problem needs (a data problem, not the model's fault)."""

def selectCandidates(client, includeWithoutTutorial: bool, noTutorialAfterDays: int, now: datetime,
                     onlyProblemId: str | None) -> list[dict]:
    columns = "id, name, rating, tags, contest_id, stage_status, hint_attempts"
    withTutorial = fetchAllRows(client, "problems", columns, "id", equals={"stage_status": WITH_TUTORIAL_STATUS})
    withoutTutorial = (
        fetchAllRows(client, "problems", columns, "id", equals={"stage_status": WITHOUT_TUTORIAL_STATUS})
        if includeWithoutTutorial else []
    )
    if onlyProblemId:
        withTutorial = [row for row in withTutorial if row["id"] == onlyProblemId]
        withoutTutorial = [row for row in withoutTutorial if row["id"] == onlyProblemId]

    contests = {contest["id"]: contest for contest in fetchContests(
        client, sorted({row["contest_id"] for row in withTutorial + withoutTutorial}))}

    def contestIsOver(row: dict, extra: timedelta) -> bool:
        contest = contests.get(row["contest_id"])
        if not contest or contest["phase"] != "FINISHED":
            return False
        start, duration = parseTimestamp(contest["start_time"]), contest["duration_seconds"]
        # Re-checked here even though the status implies it: hints must never be generated for a live contest.
        return isContestOver("FINISHED", start, duration, now) and now >= start + timedelta(seconds=duration) + extra

    # Problems not yet tried first; then the newest contest first, so a contest that just ended is not stuck behind the
    # whole backlog (ids sort as text, which would also put contest 999 after contest 2277).
    sortKey = lambda row: (row["hint_attempts"], -row["contest_id"], row["id"])
    ready = sorted((row for row in withTutorial if contestIsOver(row, timedelta())), key=sortKey)
    waited = sorted((row for row in withoutTutorial if contestIsOver(row, timedelta(days=noTutorialAfterDays))), key=sortKey)
    return ready + waited

def firstRow(response) -> dict | None:
    return response.data[0] if response.data else None

def loadProblem(client, row: dict) -> tuple[ProblemForHints, bool]:
    problemId = row["id"]
    specs = firstRow(
        client.table("problem_specifications")
        .select("time_limit_ms, memory_limit_mb, statement_text, input_specification, "
                "output_specification, interaction_specification, notes")
        .eq("problem_id", problemId)
        .execute()
    )
    if specs is None:
        raise MissingDataError(f"No problem specification stored for {problemId}.")

    samples = (
        client.table("sample_tests")
        .select("test_order, input_text, output_text")
        .eq("problem_id", problemId)
        .order("test_order")
        .execute()
        .data
    )

    tutorialText = None
    if row["stage_status"] == WITH_TUTORIAL_STATUS:
        tutorial = firstRow(client.table("tutorials").select("raw_content").eq("problem_id", problemId).execute())
        if tutorial is None or not tutorial["raw_content"].strip():
            raise MissingDataError(f"{problemId} is marked {WITH_TUTORIAL_STATUS} but has no tutorial text.")
        tutorialText = tutorial["raw_content"]

    problem = ProblemForHints(
        id=problemId, name=row["name"], rating=row["rating"], tags=row["tags"] or [],
        timeLimitMs=specs["time_limit_ms"], memoryLimitMb=specs["memory_limit_mb"],
        statementText=specs["statement_text"], inputSpecification=specs["input_specification"],
        outputSpecification=specs["output_specification"], interactionSpecification=specs["interaction_specification"],
        notes=specs["notes"], samples=[(sample["input_text"], sample["output_text"]) for sample in samples],
        tutorialText=tutorialText,
    )
    return problem, tutorialText is not None

def generateValidHints(llm, problem: ProblemForHints) -> list[Hint]:
    feedback = None
    for _ in range(1 + MAX_FORMAT_RETRIES):
        raw = llm.generate(SYSTEM_PROMPT, buildUserPrompt(problem, feedback), RESPONSE_SCHEMA)
        try:
            return validateHints(raw)
        except HintValidationError as e:
            feedback = str(e)
    raise HintValidationError(feedback)

def saveHints(client, row: dict, hints: list[Hint], model: str, grounded: bool) -> None:
    """
    The hints go in one request (all or nothing). Levels above the new count are then removed, so regenerating a
    problem with fewer hints cannot leave old ones behind to be served. The status changes last.
    """
    rows = [
        {"problem_id": row["id"], "hint_level": hint.level, "content": hint.content, "llm_model_used": model,
         "prompt_version": PROMPT_VERSION, "grounded_in_tutorial": grounded, "created_at": "now()"}
        for hint in hints
    ]
    client.table("hints").upsert(rows, on_conflict="problem_id,hint_level").execute()
    client.table("hints").delete().eq("problem_id", row["id"]).gt("hint_level", len(hints)).execute()
    (
        client.table("problems")
        .update({"stage_status": DONE_STATUS, "last_error": None, "updated_at": "now()"})
        .eq("id", row["id"])
        .eq("stage_status", row["stage_status"])
        .execute()
    )

def buildFailureUpdate(hintAttempts: int, message: str) -> dict:
    attempts = hintAttempts + 1
    update = {"hint_attempts": attempts, "last_error": message[:MAX_ERROR_CHARS], "updated_at": "now()"}
    if attempts >= MAX_HINT_ATTEMPTS:
        update["stage_status"] = "FAILED"
    return update

def run(client, llm, limit: int = DEFAULT_LIMIT, includeWithoutTutorial: bool = False,
        noTutorialAfterDays: int = DEFAULT_NO_TUTORIAL_AFTER_DAYS, dryRun: bool = False,
        onlyProblemId: str | None = None, delaySeconds: float = DEFAULT_DELAY_SECONDS,
        sleep=time.sleep, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    candidates = selectCandidates(client, includeWithoutTutorial, noTutorialAfterDays, now, onlyProblemId)[:limit]
    counts = {"generated": 0, "failed": 0, "retry_later": 0, "transient_failures": 0}
    if not candidates:
        print("No problems are ready for hints.")
        return counts

    print(f"{len(candidates)} problem(s) to process{' (dry run: nothing is written)' if dryRun else ''}.")
    consecutiveTransientFailures = 0

    def recordFailure(row: dict, message: str) -> None:
        update = buildFailureUpdate(row["hint_attempts"], message)
        if not dryRun:
            try:
                retryOnNetworkErrors(lambda: client.table("problems").update(update).eq("id", row["id"]).execute(), sleep=sleep)
            except httpx.TransportError as e:
                print(f"Could not record the failure of {row['id']} (database unreachable): {e}")
        if update.get("stage_status") == "FAILED":
            counts["failed"] += 1
            print(f"[GAVE UP -> FAILED] {row['id']} after {update['hint_attempts']} attempts: {message}")
        else:
            counts["retry_later"] += 1
            print(f"[RETRY LATER] {row['id']} (attempt {update['hint_attempts']}): {message}")

    try:
        for position, row in enumerate(candidates):
            if position > 0 and delaySeconds > 0:
                sleep(delaySeconds)

            try:
                problem, grounded = retryOnNetworkErrors(lambda: loadProblem(client, row), sleep=sleep)
                print(f"Generating hints for {row['id']} ({'with' if grounded else 'without'} editorial)...")
                hints = generateValidHints(llm, problem)
                if dryRun:
                    for hint in hints:
                        print(f"  [{row['id']}] Hint {hint.level}: {hint.content}")
                else:
                    # Safe to repeat (upsert, delete, guarded update), and retried so that an answer that was already
                    # paid for is not thrown away because of a dropped connection.
                    retryOnNetworkErrors(lambda: saveHints(client, row, hints, llm.model, grounded), sleep=sleep)
            except MissingDataError as e:
                recordFailure(row, str(e))
                continue
            except HintValidationError as e:
                recordFailure(row, f"The model's answer was rejected {1 + MAX_FORMAT_RETRIES} times: {e}")
                continue
            except (LlmBlockedError, LlmTruncatedError) as e:
                recordFailure(row, str(e))
                continue
            except (TransientLlmError, httpx.TransportError) as e:
                # A rate limit, an outage, or an unreachable database: nothing is wrong with the problem, so it keeps
                # its status and no attempt is used up.
                print(f"[RETRY LATER] {row['id']}: {e}")
                counts["transient_failures"] += 1
                consecutiveTransientFailures += 1
                if consecutiveTransientFailures >= MAX_CONSECUTIVE_TRANSIENT_FAILURES:
                    print(f"Stopping: {consecutiveTransientFailures} provider or database errors in a row. "
                          "The API or the database is probably down or rate limiting; wait before running again.")
                    break
                continue
            # An LlmRequestError (bad key, unknown model) is deliberately not caught: every call would fail.

            consecutiveTransientFailures = 0
            counts["generated"] += 1
    finally:
        # Printed however the run ends (also on a bad key), so money spent is never invisible.
        usageSummary = getattr(llm, "usageSummary", None)
        if callable(usageSummary):
            print(f"Usage: {usageSummary()}")

    print(f"Done. Generated: {counts['generated']}, failed: {counts['failed']}, will retry: {counts['retry_later']}, "
          f"provider errors: {counts['transient_failures']}.")
    return counts

def main():
    parser = argparse.ArgumentParser(description="Generate graded hints (2 to 5, depending on the problem) for problems that are ready.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"Maximum problems this run (default {DEFAULT_LIMIT}); each costs model calls.")
    parser.add_argument("--dry-run", action="store_true", help="Call the model and print the hints, but write nothing.")
    parser.add_argument("--problem", help="Only this problem id, e.g. 1943_A.")
    parser.add_argument("--include-without-tutorial", action="store_true",
                        help="Also take problems still WAITING_FOR_TUTORIAL once their contest is old enough; "
                             "those hints are marked as not grounded in a tutorial.")
    parser.add_argument("--no-tutorial-after-days", type=int, default=DEFAULT_NO_TUTORIAL_AFTER_DAYS,
                        help=f"How long after a contest ends to give up waiting for its tutorial (default {DEFAULT_NO_TUTORIAL_AFTER_DAYS}).")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS, help=f"Seconds between model calls (default {DEFAULT_DELAY_SECONDS}).")
    args = parser.parse_args()

    # Imported here so the module can be imported (e.g. by tests) without database credentials.
    from src.core.database.dbClient import supabase
    try:
        run(supabase, createClientFromEnvironment(), args.limit, args.include_without_tutorial,
            args.no_tutorial_after_days, args.dry_run, args.problem, args.delay)
    except LlmRequestError as e:
        print(f"Stopping: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
