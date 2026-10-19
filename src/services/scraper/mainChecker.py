import argparse
import time
import traceback
from src.services.scraper.errors import ScrapingValidationError, TransientScrapeError
from src.services.scraper.problemParser import parse_problem_details_strictly
from src.services.scraper.problemScraper import scrapeProblemPage

# A problem that keeps failing for transient reasons is given up on after this many attempts.
MAX_SCRAPE_ATTEMPTS = 5
# Several blocked/failed requests in a row mean we are being blocked: stop instead of hammering the site.
MAX_CONSECUTIVE_TRANSIENT_FAILURES = 5
# Supabase returns at most 1000 rows per request.
DEFAULT_LIMIT = 1000
DEFAULT_DELAY_SECONDS = 2.0

def buildTransientFailureUpdate(scrapeAttempts: int, message: str) -> dict:
    """The problem stays DISCOVERED (retried on a later run) until it has used up its attempts."""
    attempts = scrapeAttempts + 1
    update = {"scrape_attempts": attempts, "last_error": message, "updated_at": "now()"}
    if attempts >= MAX_SCRAPE_ATTEMPTS:
        update["stage_status"] = "FAILED"
    return update

def markFailed(client, problemId: str, message: str):
    client.table("problems").update({
        "stage_status": "FAILED",
        "last_error": message,
        "updated_at": "now()"
    }).eq("id", problemId).execute()

def checkAndProcessProblem(client, limit: int = DEFAULT_LIMIT, delaySeconds: float = DEFAULT_DELAY_SECONDS,
                           fetchPage=scrapeProblemPage, sleep=time.sleep) -> dict[str, int]:
    response = (
        client.table("problems")
        .select("id, contest_id, index, scrape_attempts")
        .eq("stage_status", "DISCOVERED")
        .order("scrape_attempts")
        .order("id")
        .limit(limit)
        .execute()
    )

    problems = response.data
    counts = {"scraped": 0, "failed": 0, "retry_later": 0}
    if not problems:
        print("No problems found with status 'DISCOVERED'.")
        return counts

    print(f"Found {len(problems)} problem(s) to process.")

    consecutiveTransientFailures = 0

    for position, problem in enumerate(problems):
        problemId = problem["id"]
        contestId = problem["contest_id"]
        index = problem["index"]

        if position > 0 and delaySeconds > 0:
            sleep(delaySeconds)

        try:
            print(f"Scraping Contest {contestId}, Index {index} (ID: {problemId})...")
            soup = fetchPage(contestId, index)

            specs, samples = parse_problem_details_strictly(soup)
            specs["problem_id"] = problemId
            for sample in samples:
                sample["problem_id"] = problemId

            # Upsert both tables cleanly
            client.table("problem_specifications").upsert(specs).execute()
            if samples:  # a few problems have none, and an empty upsert would be a pointless request
                client.table("sample_tests").upsert(samples).execute()

            # Update status ONLY after all data is safely stored
            client.table("problems").update({
                "stage_status": "SCRAPED_WAITING_FOR_CONTEST",
                "last_error": None,
                "updated_at": "now()"
            }).eq("id", problemId).execute()

            counts["scraped"] += 1
            consecutiveTransientFailures = 0
            print(f"Successfully verified and saved ID: {problemId} (with {len(samples)} sample tests)")

        except TransientScrapeError as te:
            update = buildTransientFailureUpdate(problem["scrape_attempts"], str(te))
            client.table("problems").update(update).eq("id", problemId).execute()

            if update.get("stage_status") == "FAILED":
                counts["failed"] += 1
                print(f"[GAVE UP -> FAILED] Problem {problemId} after {update['scrape_attempts']} attempts: {te}")
            else:
                counts["retry_later"] += 1
                print(f"[RETRY LATER] Problem {problemId} (attempt {update['scrape_attempts']}): {te}")

            consecutiveTransientFailures += 1
            if consecutiveTransientFailures >= MAX_CONSECUTIVE_TRANSIENT_FAILURES:
                print(f"Stopping: {consecutiveTransientFailures} transient failures in a row. "
                      "Codeforces is probably blocking or rate limiting us; wait before running again.")
                break

        except ScrapingValidationError as ve:
            print(f"[REJECTED -> FAILED] Problem {problemId} failed strict validation: {str(ve)}")
            markFailed(client, problemId, str(ve))
            counts["failed"] += 1
            consecutiveTransientFailures = 0

        except Exception as e:
            print(f"[CRITICAL ERROR -> FAILED] Unexpected system failure for problem {problemId}: {str(e)}")
            traceback.print_exc()

            try:
                markFailed(client, problemId, f"Unexpected error: {e}")
            except Exception as db_err:
                print(f"Could not even update status to FAILED for {problemId}: {str(db_err)}")
            counts["failed"] += 1

    print(f"Done. Scraped: {counts['scraped']}, failed: {counts['failed']}, will retry: {counts['retry_later']}.")
    return counts

def main():
    parser = argparse.ArgumentParser(description="Scrape DISCOVERED problems from Codeforces into the database.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"Maximum problems to process this run (default {DEFAULT_LIMIT}, the Supabase page cap).")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS,
                        help=f"Seconds to wait between requests (default {DEFAULT_DELAY_SECONDS}).")
    args = parser.parse_args()

    # Imported here so the module can be imported (e.g. by tests) without database credentials.
    from src.core.database.dbClient import supabase
    checkAndProcessProblem(supabase, args.limit, args.delay)

if __name__ == "__main__":
    main()
