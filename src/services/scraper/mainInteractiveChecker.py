import re
import traceback
from bs4 import BeautifulSoup
from src.core.database.dbClient import supabase
from src.services.scraper.problemScraper import scrapeProblemPage

class ScrapingValidationError(Exception):
    """Raised when scraped content fails strict validation requirements."""
    pass

def parse_problem_details_strictly(soup: BeautifulSoup) -> tuple[dict, list[dict]]:
    """
    Extracts problem specifications and sample tests strictly. 
    Raises ScrapingValidationError if ANY required field is missing, empty, or unparseable.
    Zero fallbacks allowed.
    Returns: (specs_dict, samples_list)
    """
    # --- 1. PARSE LIMITS & STATEMENT ---
    timeElement = soup.select_one(".problem-statement .header .time-limit")
    if not timeElement:
        raise ScrapingValidationError("Time limit element not found in DOM.")
    
    timeMatch = re.search(r"([\d\.]+)", timeElement.get_text())
    if not timeMatch:
        raise ScrapingValidationError(f"Could not parse numeric time limit from text: '{timeElement.get_text()}'")
    timeLimitMS = int(float(timeMatch.group(1)) * 1000)

    memoryElement = soup.select_one(".problem-statement .header .memory-limit")
    if not memoryElement:
        raise ScrapingValidationError("Memory limit element not found in DOM.")
    
    memoryMatch = re.search(r"(\d+)", memoryElement.get_text())
    if not memoryMatch:
        raise ScrapingValidationError(f"Could not parse numeric memory limit from text: '{memoryElement.get_text()}'")
    memoryLimitMS = int(memoryMatch.group(1))

    problemStatementDiv = soup.select_one(".problem-statement")
    if not problemStatementDiv:
        raise ScrapingValidationError("Main '.problem-statement' container not found.")
    
    childDivs = problemStatementDiv.find_all("div", recursive=False)
    if len(childDivs) < 2 or childDivs[1].get("class"):
        raise ScrapingValidationError("Problem statement text div not found at expected DOM hierarchy index.")
    
    statementText = childDivs[1].get_text(separator="\n\n", strip=True)
    if not statementText:
        raise ScrapingValidationError("Extracted problem statement text is empty.")

    # --- 2. PARSE SPECS & NOTES ---
    def getRequiredText(selector: str, field_name: str) -> str:
        elem = soup.select_one(selector)
        if not elem:
            raise ScrapingValidationError(f"Required element '{selector}' ({field_name}) not found.")
        text = elem.get_text(separator="\n", strip=True)
        if not text:
            raise ScrapingValidationError(f"Extracted text for '{field_name}' is empty.")
        return text

    inputSpec = getRequiredText(".problem-statement .input-specification", "input_specification")

    # The main difference between mainChecker and mainInteractiveChecker is here...
    # STRICT INTERACTION PARSING (Replaces Output Specification)
    interactionTitle = soup.find(
        "div", 
        class_="section-title", 
        string=lambda text: text and "Interaction" in text
    )
    if not interactionTitle:
        raise ScrapingValidationError("Required 'Interaction' section title not found in DOM.")
        
    interactionContainer = interactionTitle.parent
    interactionSpec = interactionContainer.get_text(separator="\n", strip=True)
    if not interactionSpec:
        raise ScrapingValidationError("Extracted text for 'Interaction' section is empty.")

    noteElement = soup.select_one(".problem-statement .note")
    notes = noteElement.get_text(separator="\n", strip=True) if noteElement else None

    # --- 3. STRICTLY PARSE SAMPLE TESTS ---
    sampleContainer = soup.select_one(".problem-statement .sample-tests .sample-test")
    if not sampleContainer:
        raise ScrapingValidationError("Sample tests container '.sample-test' not found in DOM.")

    inputElems = sampleContainer.select(".input pre")
    outputElems = sampleContainer.select(".output pre")

    if not inputElems or not outputElems:
        raise ScrapingValidationError("Could not find any '<pre>' tags inside sample inputs/outputs.")
    
    if len(inputElems) != len(outputElems):
        raise ScrapingValidationError(f"Mismatched samples: found {len(inputElems)} inputs and {len(outputElems)} outputs.")

    samples = []
    for idx, (inElem, outElem) in enumerate(zip(inputElems, outputElems), start=1):
        inText = inElem.get_text(separator="\n", strip=True)
        outText = outElem.get_text(separator="\n", strip=True)
        
        if inText == "" or outText == "":
            raise ScrapingValidationError(f"Sample test #{idx} contains empty input or output text.")
            
        samples.append({
            "test_order": idx,
            "input_text": inText,
            "output_text": outText
        })

    specs = {
        "time_limit_ms": timeLimitMS,
        "memory_limit_ms": memoryLimitMS,
        "statement_text": statementText,
        "input_specification": inputSpec,
        "output_specification": interactionSpec, 
        "notes": notes
    }

    return specs, samples

def checkAndProcessProblem():
    response = (
        supabase.table("problems")
        .select("id, contest_id, index")
        .eq("stage_status", "DISCOVERED")
        .limit(15000)
        .execute()
    )
    
    problems = response.data
    if not problems:
        print("No problems found with status 'DISCOVERED'.")
        return

    print(f"Found {len(problems)} problem(s) to process.")

    for problem in problems:
        problemId = problem["id"]
        contestId = problem["contest_id"]
        index = problem["index"]
        
        try:
            print(f"Scraping Contest {contestId}, Index {index} (ID: {problemId})...")
            soup = scrapeProblemPage(contestId, index)
            
            if not soup:
                raise ScrapingValidationError("Scraper returned empty HTML / failed to fetch page.")
                
            specs, samples = parse_problem_details_strictly(soup)
            specs["problem_id"] = problemId
            for sample in samples:
                sample["problem_id"] = problemId
            
            # Upsert both tables cleanly
            supabase.table("interactive_problem_specifications").upsert(specs).execute()
            supabase.table("sample_tests").upsert(samples).execute()
            
            # Update status ONLY after all data is safely stored
            supabase.table("problems").update({
                "stage_status": "SCRAPED_WAITING_FOR_CONTEST",
                "updated_at": "now()"
            }).eq("id", problemId).execute()
            
            print(f"Successfully verified and saved ID: {problemId} (with {len(samples)} sample tests)")
                
        except ScrapingValidationError as ve:
            print(f"[REJECTED -> FAILED] Problem {problemId} failed strict validation: {str(ve)}")
            
            supabase.table("problems").update({
                "stage_status": "FAILED",
                "updated_at": "now()"
            }).eq("id", problemId).execute()
            
        except Exception as e:
            print(f"[CRITICAL ERROR -> FAILED] Unexpected system failure for problem {problemId}: {str(e)}")
            traceback.print_exc()
            
            try:
                supabase.table("problems").update({
                    "stage_status": "FAILED",
                    "updated_at": "now()"
                }).eq("id", problemId).execute()
            except Exception as db_err:
                print(f"Could not even update status to FAILED for {problemId}: {str(db_err)}")

if __name__ == "__main__":
    checkAndProcessProblem()