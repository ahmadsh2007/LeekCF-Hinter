import argparse
import csv
from src.utils.statementHash import computeStatementHash
from src.utils.supabasePaging import fetchAllRows
from src.workers.dedup.dedupPlanner import DedupPlan, DedupProblem, planDedup

FETCH_CHUNK_SIZE = 100  # problem ids travel in the URL of an in_(...) filter
SAVE_BATCH_SIZE = 200   # specs rows carry whole statements, so keep write requests small
LINK_CHUNK_SIZE = 100
SAMPLE_LINKS_TO_PRINT = 20
REPORT_COLUMNS = ["group", "problem_id", "name", "contest_id", "start_time", "statement_hash"]

def buildDedupProblems(problemRows: list[dict], contestRows: list[dict], hashByProblemId: dict[str, str]) -> list[DedupProblem]:
    startTimeByContestId = {contest["id"]: contest["start_time"] for contest in contestRows}
    return [
        DedupProblem(
            id=row["id"],
            name=row["name"],
            contestId=row["contest_id"],
            stageStatus=row["stage_status"],
            canonicalProblemId=row["canonical_problem_id"],
            startTime=startTimeByContestId[row["contest_id"]],
            statementHash=hashByProblemId.get(row["id"]),
        )
        for row in problemRows
    ]

def loadStatementHashes(client) -> tuple[dict[str, str], list[dict]]:
    """
    Returns (hash by problem id, full specs rows whose hash was missing and has just been computed).
    Computing is in memory only; saving the rows is saveHashes' job, so a dry run writes nothing.
    """
    hashes: dict[str, str] = {}
    missing: list[str] = []
    for row in fetchAllRows(client, "problem_specifications", "problem_id, statement_hash", "problem_id"):
        if row["statement_hash"]:
            hashes[row["problem_id"]] = row["statement_hash"]
        else:
            missing.append(row["problem_id"])

    backfillRows: list[dict] = []
    for start in range(0, len(missing), FETCH_CHUNK_SIZE):
        chunk = missing[start:start + FETCH_CHUNK_SIZE]
        rows = client.table("problem_specifications").select("*").in_("problem_id", chunk).execute().data
        for row in rows:
            row["statement_hash"] = computeStatementHash(row)
            hashes[row["problem_id"]] = row["statement_hash"]
            backfillRows.append(row)

    return hashes, backfillRows

def saveHashes(client, rows: list[dict]):
    # Whole rows are upserted: an upsert is an INSERT first, so partial rows would trip NOT NULL columns.
    for start in range(0, len(rows), SAVE_BATCH_SIZE):
        client.table("problem_specifications").upsert(rows[start:start + SAVE_BATCH_SIZE]).execute()

def applyLinks(client, links: list[tuple[str, str]]):
    duplicatesByCanonical: dict[str, list[str]] = {}
    for duplicateId, canonicalId in links:
        duplicatesByCanonical.setdefault(canonicalId, []).append(duplicateId)

    for canonicalId, duplicateIds in duplicatesByCanonical.items():
        for start in range(0, len(duplicateIds), LINK_CHUNK_SIZE):
            client.table("problems").update({
                "stage_status": "DUPLICATE",
                "canonical_problem_id": canonicalId,
                "updated_at": "now()"
            }).in_("id", duplicateIds[start:start + LINK_CHUNK_SIZE]).execute()

def writeReviewReport(path: str, reviews: list[list[DedupProblem]]):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        for groupNumber, group in enumerate(reviews, start=1):
            for member in group:
                writer.writerow({
                    "group": groupNumber,
                    "problem_id": member.id,
                    "name": member.name,
                    "contest_id": member.contestId,
                    "start_time": member.startTime,
                    "statement_hash": member.statementHash,
                })

def run(client, apply: bool, reportPath: str | None) -> DedupPlan:
    hashes, backfillRows = loadStatementHashes(client)
    problemRows = fetchAllRows(client, "problems", "id, name, contest_id, stage_status, canonical_problem_id", "id")
    contestRows = fetchAllRows(client, "contests", "id, start_time", "id")

    plan = planDedup(buildDedupProblems(problemRows, contestRows, hashes))

    print(f"Problems loaded: {len(problemRows)}. Statement hashes to save: {len(backfillRows)}.")
    print(f"Duplicates to link: {len(plan.links)}. Groups needing review (same name and start time, different statement): {len(plan.reviews)}.")
    for duplicateId, canonicalId in plan.links[:SAMPLE_LINKS_TO_PRINT]:
        print(f"  {duplicateId} -> {canonicalId}")
    if len(plan.links) > SAMPLE_LINKS_TO_PRINT:
        print(f"  ... and {len(plan.links) - SAMPLE_LINKS_TO_PRINT} more")
    for group in plan.reviews:
        print("  REVIEW: " + ", ".join(f"{member.id} ({member.statementHash[:8]})" for member in group))

    if reportPath:
        writeReviewReport(reportPath, plan.reviews)
        print(f"Review report written to {reportPath}")

    if apply:
        saveHashes(client, backfillRows)
        applyLinks(client, plan.links)
        print("Applied.")
    else:
        print("Dry run: nothing was written. Re-run with --apply to save.")

    return plan

def main():
    parser = argparse.ArgumentParser(description="Find Div1/Div2 duplicates and link them to one canonical problem.")
    parser.add_argument("--apply", action="store_true", help="Write the hashes and links. Without it nothing is changed.")
    parser.add_argument("--report", metavar="PATH", help="Write the groups that need human review to this CSV file.")
    args = parser.parse_args()

    # Imported here so the module can be imported (e.g. by tests) without database credentials.
    from src.core.database.dbClient import supabase
    run(supabase, args.apply, args.report)

if __name__ == "__main__":
    main()
