import argparse
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import httpx
from src.utils.retry import retryOnNetworkErrors

# Cloudflare's Analytics Engine keeps what the Worker writes for three months only. This copies the daily totals into
# the project's own database, where they stay for as long as the project does (migration 005). Run it once a day.
DATASET = "hinter_requests"          # the dataset bound as ANALYTICS in wrangler.toml
TABLE = "api_usage_daily"
CONFLICT_KEY = "day,client,route,status"
DEFAULT_DAYS = 7                     # read this many days back every run, so a missed run heals itself
RETENTION_DAYS = 90                  # how far back Cloudflare keeps data
SAVE_CHUNK_SIZE = 500
SQL_ENDPOINT = "https://api.cloudflare.com/client/v4/accounts/{account}/analytics_engine/sql"

class UsageSourceError(Exception):
    pass

def buildQuery(days: int) -> str:
    """
    The Worker writes blobs [route, status, client] and doubles [response time ms, 1 if served from the edge cache].
    Analytics Engine may sample busy datasets; _sample_interval says how many requests one stored point stands for.
    """
    return (
        "SELECT toStartOfInterval(timestamp, INTERVAL '1' DAY) AS day, blob1 AS route, blob2 AS status, blob3 AS client, "
        "SUM(_sample_interval) AS requests, SUM(_sample_interval * double2) AS cache_hits, "
        "SUM(_sample_interval * double1) AS total_duration_ms "
        f"FROM {DATASET} WHERE timestamp > NOW() - INTERVAL '{days}' DAY "
        "GROUP BY day, route, status, client ORDER BY day FORMAT JSON"
    )

def firstCompleteDay(now: datetime, days: int) -> date:
    """The window starts in the middle of a day; that day is cut short, so it is never saved from this window."""
    return (now - timedelta(days=days)).date() + timedelta(days=1)

def windowDays(lastSavedDay: date | None, today: date, default: int = DEFAULT_DAYS, maximum: int = RETENTION_DAYS) -> int:
    """Long enough to read the last saved day again (it was unfinished when saved), and never longer than Cloudflare keeps."""
    if lastSavedDay is None:
        return default
    return min(max(default, (today - lastSavedDay).days + 1), maximum)

def toRows(records: list[dict], firstDay: date) -> list[dict]:
    rows = []
    for record in records:
        try:
            day = str(record["day"])[:10]
            row = {
                "day": day,
                "route": str(record["route"]),
                "status": int(float(record["status"])),
                "client": str(record["client"]),
                "requests": int(float(record["requests"])),
                "cache_hits": int(float(record["cache_hits"])),
                "total_duration_ms": float(record["total_duration_ms"]),
            }
            isOld = date.fromisoformat(day) < firstDay
        except (KeyError, TypeError, ValueError) as e:
            raise UsageSourceError(f"Unexpected row from the analytics query ({type(e).__name__}: {e}): {str(record)[:200]}") from e
        if not isOld:
            rows.append(row)
    return rows

class CloudflareUsageSource:
    def __init__(self, accountId: str, apiToken: str, http: httpx.Client | None = None):
        self.accountId = accountId
        self.apiToken = apiToken
        self.http = http or httpx.Client(timeout=60.0)

    def fetch(self, query: str) -> list[dict]:
        response = self.http.post(
            SQL_ENDPOINT.format(account=self.accountId),
            headers={"Authorization": f"Bearer {self.apiToken}"},
            content=query,
        )
        if response.status_code != 200:
            raise UsageSourceError(f"Cloudflare answered {response.status_code}: {response.text[:300]}")
        try:
            return response.json()["data"]
        except (ValueError, KeyError, TypeError) as e:
            raise UsageSourceError(f"Cloudflare's answer was not the expected JSON: {response.text[:200]}") from e

def readCredentials(environ) -> tuple[str, str] | None:
    accountId, apiToken = environ.get("CLOUDFLARE_ACCOUNT_ID"), environ.get("CLOUDFLARE_API_TOKEN")
    return (accountId, apiToken) if accountId and apiToken else None

def lastSavedDay(client) -> date | None:
    rows = client.table(TABLE).select("day").order("day", desc=True).limit(1).execute().data
    return date.fromisoformat(str(rows[0]["day"])[:10]) if rows else None

def saveRows(client, rows: list[dict]) -> None:
    for start in range(0, len(rows), SAVE_CHUNK_SIZE):
        client.table(TABLE).upsert(rows[start:start + SAVE_CHUNK_SIZE], on_conflict=CONFLICT_KEY).execute()

def run(client, source, now: datetime | None = None, days: int = DEFAULT_DAYS, sleep=time.sleep) -> int:
    now = now or datetime.now(timezone.utc)
    last = retryOnNetworkErrors(lambda: lastSavedDay(client), sleep=sleep)
    window = windowDays(last, now.date(), default=days)
    if window > days:
        print(f"The last saved day is {last}; reading {window} days so nothing is missed.")
    rows = toRows(source.fetch(buildQuery(window)), firstCompleteDay(now, window))
    if rows:
        retryOnNetworkErrors(lambda: saveRows(client, rows), sleep=sleep)
    print(f"Saved {len(rows)} daily usage row(s) covering {len({row['day'] for row in rows})} day(s).")
    return len(rows)

def main():
    parser = argparse.ArgumentParser(description="Copy the API's daily usage statistics from Cloudflare into the database.")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"Days to read back every run (default {DEFAULT_DAYS}).")
    parser.add_argument("--if-configured", action="store_true",
                        help="Do nothing, successfully, when the Cloudflare settings are missing (for the daily pipeline).")
    args = parser.parse_args()

    # Imported here so the module can be imported (e.g. by tests) without database credentials. It also loads ENV_FILE.
    from src.core.database.dbClient import supabase
    credentials = readCredentials(os.environ)
    if credentials is None:
        if args.if_configured:
            print("Skipped: CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN are not set, so the usage statistics are not saved.")
            return
        print("Stopping: set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN (a token with 'Account Analytics: Read') in the env file.")
        sys.exit(2)
    try:
        run(supabase, CloudflareUsageSource(*credentials), days=args.days)
    except (UsageSourceError, httpx.TransportError) as e:
        print(f"Stopping: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
