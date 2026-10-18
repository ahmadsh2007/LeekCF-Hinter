import argparse
from datetime import datetime, timedelta, timezone
from src.utils.supabasePaging import fetchAllRows

# Extra wait after a contest's scheduled end for system tests (keep in sync with migrations/004_public_hints_view.sql).
COOLDOWN = timedelta(hours=2)
WAITING_STATUS = "SCRAPED_WAITING_FOR_CONTEST"
NEXT_STATUS = "WAITING_FOR_TUTORIAL"
FETCH_CHUNK_SIZE = 100    # contest ids travel in the URL of an in_(...) filter
PROMOTE_CHUNK_SIZE = 100  # so do the problem ids of an update

def parseTimestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)

def isContestOver(phase: str, startTime: datetime, durationSeconds: int, now: datetime) -> bool:
    """
    Both conditions are required. The stored phase can only be stale in the safe direction (a finished contest
    still marked CODING just waits), and the clock rule catches a phase flag that was set too early.
    """
    return phase == "FINISHED" and now >= startTime + timedelta(seconds=durationSeconds) + COOLDOWN

def planPromotions(problems: list[dict], contests: list[dict], now: datetime) -> list[str]:
    """Ids of the waiting problems whose contest is over. A problem whose contest row is missing stays put."""
    contestsById = {contest["id"]: contest for contest in contests}
    promotable = []
    for problem in problems:
        contest = contestsById.get(problem["contest_id"])
        if problem["stage_status"] == WAITING_STATUS and contest and isContestOver(
            contest["phase"], parseTimestamp(contest["start_time"]), contest["duration_seconds"], now
        ):
            promotable.append(problem["id"])
    return promotable

def fetchContests(client, contestIds: list[int]) -> list[dict]:
    contests: list[dict] = []
    for start in range(0, len(contestIds), FETCH_CHUNK_SIZE):
        chunk = contestIds[start:start + FETCH_CHUNK_SIZE]
        contests.extend(
            client.table("contests")
            .select("id, phase, start_time, duration_seconds")
            .in_("id", chunk)
            .execute()
            .data
        )
    return contests

def run(client, now: datetime | None = None, dryRun: bool = False) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    problems = fetchAllRows(client, "problems", "id, contest_id, stage_status", "id", equals={"stage_status": WAITING_STATUS})
    contests = fetchContests(client, sorted({problem["contest_id"] for problem in problems}))
    promotable = planPromotions(problems, contests, now)

    if not dryRun:
        for start in range(0, len(promotable), PROMOTE_CHUNK_SIZE):
            chunk = promotable[start:start + PROMOTE_CHUNK_SIZE]
            # The status guard keeps this from touching a row another worker has moved on.
            (
                client.table("problems")
                .update({"stage_status": NEXT_STATUS, "updated_at": "now()"})
                .in_("id", chunk)
                .eq("stage_status", WAITING_STATUS)
                .execute()
            )

    counts = {"promoted": len(promotable), "still_waiting": len(problems) - len(promotable)}
    verb = "Would promote" if dryRun else "Promoted"
    print(f"{verb} {counts['promoted']} problem(s) to {NEXT_STATUS}; {counts['still_waiting']} still waiting for their contest to finish.")
    return counts

def main():
    parser = argparse.ArgumentParser(description="Move problems whose contest is over to WAITING_FOR_TUTORIAL.")
    parser.add_argument("--dry-run", action="store_true", help="Report what would move without changing anything.")
    args = parser.parse_args()

    # Imported here so the module can be imported (e.g. by tests) without database credentials.
    from src.core.database.dbClient import supabase
    run(supabase, dryRun=args.dry_run)

if __name__ == "__main__":
    main()
