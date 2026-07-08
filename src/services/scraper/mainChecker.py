from src.core.database.dbClient import supabase
from src.services.scraper.problemScraper import scrapeProblemPage

def checkAndProcessProblem():
    # Check for problems with 'DISCOVERED' status
    response = (
        supabase.table("problems")
        .select("id, contest_id, index")
        .eq("stage_status", "DISCOVERED")
        .limit(15)
        .execute()
    )
    
    problems = response.data
    if not problems:
        print("No problems found with status 'DISCOVERED'.")
        return

    print(f"Found {len(problems)} problem(s) to process.")

    # for problem in problems:
    #     problemId = problem["id"]
    #     contestId = problem["contest_id"]
    #     index = problem["index"]
        
    #     soup = scrapeProblemPage(contestId, index)
        
    #     if soup:
    #         supabase.table("problems").update({
    #             "stage_status": "SCRAPED_WAITING_FOR_CONTEST",
    #             "updated_at": "now()"
    #         }).eq("id", problemId).execute()
            
    #         print(f"Successfully processed and updated status for {problemId}")
    #     else:
    #         print(f"Skipping DB update for {problemId} due to scraping failure.")

if __name__ == "__main__":
    checkAndProcessProblem()