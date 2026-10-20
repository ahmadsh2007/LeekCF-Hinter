import argparse
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from src.utils.supabasePaging import fetchAllRows

# One line per stage a problem can be in, in the order it passes through them.
STATUSES = [
    ("DISCOVERED", "found, statement not scraped yet"),
    ("SCRAPED_WAITING_FOR_CONTEST", "scraped, waiting for the contest to end"),
    ("WAITING_FOR_TUTORIAL", "contest over, waiting for a tutorial"),
    ("TUTORIAL_FOUND", "tutorial found, waiting for hints"),
    ("HINTS_GENERATED", "hints ready"),
    ("FAILED", "failed"),
    ("DUPLICATE", "copy of another problem"),
]
RECENT_HOURS = 24
SCRAPE_OVERDUE_HOURS = 48       # a statement is normally scraped within a day of being found
REASON_LENGTH = 100

@dataclass
class Snapshot:
    now: datetime
    counts: dict[str, int]
    newProblems: int
    hintsWritten: int
    problemsWithNewHints: int
    hintModels: dict[str, int]
    lastHintAt: datetime | None
    failedReasons: dict[str, int]
    overdueScrapes: int
    apiRequestsYesterday: int | None

def parseTime(text: str) -> datetime:
    return datetime.fromisoformat(text)

def countRows(client, table: str, **filters) -> int:
    query = client.table(table).select("id", count="exact")
    for column, value in filters.get("equals", {}).items():
        query = query.eq(column, value)
    for column, value in filters.get("greaterThan", {}).items():
        query = query.gt(column, value)
    return query.range(0, 0).execute().count

def collectSnapshot(client, now: datetime) -> Snapshot:
    since = (now - timedelta(hours=RECENT_HOURS)).isoformat()
    overdueBefore = now - timedelta(hours=SCRAPE_OVERDUE_HOURS)

    counts = {status: countRows(client, "problems", equals={"stage_status": status}) for status, _ in STATUSES}
    recentHints = fetchAllRows(client, "hints", "id,problem_id,llm_model_used,created_at", "id", greaterThan={"created_at": since})
    latest = client.table("hints").select("created_at").order("created_at", desc=True).limit(1).execute().data

    failed = fetchAllRows(client, "problems", "id,last_error", "id", equals={"stage_status": "FAILED"})
    reasons = Counter((row["last_error"] or "(no reason recorded)")[:REASON_LENGTH] for row in failed)

    unscraped = fetchAllRows(client, "problems", "id,created_at", "id", equals={"stage_status": "DISCOVERED"})
    overdue = sum(1 for row in unscraped if parseTime(row["created_at"]) < overdueBefore)

    yesterday = (now.date() - timedelta(days=1)).isoformat()
    usage = fetchAllRows(client, "api_usage_daily", "requests", ["day", "client", "route", "status"], equals={"day": yesterday})

    return Snapshot(
        now=now,
        counts=counts,
        newProblems=countRows(client, "problems", greaterThan={"created_at": since}),
        hintsWritten=len(recentHints),
        problemsWithNewHints=len({row["problem_id"] for row in recentHints}),
        hintModels=dict(Counter(row["llm_model_used"] for row in recentHints).most_common()),
        lastHintAt=parseTime(latest[0]["created_at"]) if latest else None,
        failedReasons=dict(reasons.most_common()),
        overdueScrapes=overdue,
        apiRequestsYesterday=sum(row["requests"] for row in usage) if usage else None,
    )

def plural(count: int, noun: str) -> str:
    return f"{count:,} {noun}" if count == 1 else f"{count:,} {noun}s"

def findWarnings(snapshot: Snapshot) -> list[str]:
    """What a green run can hide: the stages stop quietly when Codeforces blocks them or a model has no quota left."""
    warnings = []
    waiting = snapshot.counts["TUTORIAL_FOUND"]
    if waiting > 0 and snapshot.hintsWritten == 0:
        warnings.append(
            f"No hint was written in the last {RECENT_HOURS} hours although {plural(waiting, 'problem')} with a tutorial are waiting. "
            "The model quota may be used up, the key may be wrong, or the model is failing: read stage 5 of the latest run."
        )
    if snapshot.overdueScrapes > 0:
        warnings.append(
            f"{plural(snapshot.overdueScrapes, 'problem')} have waited more than {SCRAPE_OVERDUE_HOURS // 24} days to be scraped. "
            "Codeforces may be refusing the connection: read stage 1 of the latest run."
        )
    return warnings

def ago(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{plural(max(minutes, 0), 'minute')} ago"
    if minutes < 48 * 60:
        return f"{plural(minutes // 60, 'hour')} ago"
    return f"{plural(minutes // (24 * 60), 'day')} ago"

def renderReport(snapshot: Snapshot, warnings: list[str]) -> str:
    lines = [f"## LeekCF-Hinter status, {snapshot.now.strftime('%Y-%m-%d %H:%M')} UTC", "",
             f"{plural(sum(snapshot.counts.values()), 'problem')}:"]
    lines += [f"- {snapshot.counts[status]:,} {meaning}" for status, meaning in STATUSES]

    lines += ["", f"Last {RECENT_HOURS} hours:", f"- {plural(snapshot.newProblems, 'new problem')} found"]
    models = ", ".join(f"{model}: {count}" for model, count in snapshot.hintModels.items())
    lines.append(f"- {plural(snapshot.hintsWritten, 'hint')} written for {plural(snapshot.problemsWithNewHints, 'problem')}"
                 + (f" ({models})" if models else ""))
    lines.append(f"- Latest hint written {ago(snapshot.now - snapshot.lastHintAt)}." if snapshot.lastHintAt
                 else "- No hint has been written yet.")
    lines.append(f"- {snapshot.apiRequestsYesterday:,} API requests yesterday" if snapshot.apiRequestsYesterday is not None
                 else "- There are no saved API statistics for yesterday yet.")

    if snapshot.failedReasons:
        lines += ["", f"Failed problems ({snapshot.counts['FAILED']:,}):"]
        lines += [f"- {count} x {reason}" for reason, count in snapshot.failedReasons.items()]

    lines.append("")
    lines += [f"WARNING: {warning}" for warning in warnings] or ["No warnings."]
    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser(description="Print how the pipeline is doing: problems per stage, the last day's work, and warnings.")
    parser.add_argument("--strict", action="store_true", help="Exit with an error when there is a warning (for the daily run, so GitHub reports it).")
    parser.add_argument("--append-to", metavar="FILE", help="Also append the report to this file (GitHub shows $GITHUB_STEP_SUMMARY on the run's page).")
    args = parser.parse_args()

    # Imported here so the module can be imported (e.g. by tests) without database credentials. It also loads ENV_FILE.
    from src.core.database.dbClient import supabase
    snapshot = collectSnapshot(supabase, datetime.now(timezone.utc))
    warnings = findWarnings(snapshot)
    report = renderReport(snapshot, warnings)
    print(report)
    if args.append_to:
        with open(args.append_to, "a", encoding="utf-8") as handle:
            handle.write(report + "\n")
    if warnings and args.strict:
        sys.exit(1)

if __name__ == "__main__":
    main()
