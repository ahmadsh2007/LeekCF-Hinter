import re
from bs4 import BeautifulSoup
from src.services.scraper.errors import ScrapingValidationError
from src.utils.statementHash import computeStatementHash

def getSectionText(elem, field_name: str) -> str:
    text = elem.get_text(separator="\n", strip=True)
    if not text:
        raise ScrapingValidationError(f"Extracted text for '{field_name}' is empty.")
    return text

def parse_problem_details_strictly(soup: BeautifulSoup) -> tuple[dict, list[dict]]:
    """
    Extracts problem specifications and sample tests strictly, for standard and interactive problems alike.
    Raises ScrapingValidationError if ANY required field is missing, empty, or unparseable.
    Zero fallbacks allowed.
    A problem is interactive when its statement has an "Interaction" section; a page needs an Output
    section, an Interaction section, or both.
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
    memoryLimitMB = int(memoryMatch.group(1))

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
    inputElement = soup.select_one(".problem-statement .input-specification")
    if not inputElement:
        raise ScrapingValidationError("Required element '.problem-statement .input-specification' (input_specification) not found.")
    inputSpec = getSectionText(inputElement, "input_specification")

    outputElement = soup.select_one(".problem-statement .output-specification")
    outputSpec = getSectionText(outputElement, "output_specification") if outputElement else None

    interactionSpec = None
    interactionTitle = problemStatementDiv.find(
        "div",
        class_="section-title",
        string=lambda text: text and "Interaction" in text
    )
    if interactionTitle:
        interactionSpec = getSectionText(interactionTitle.parent, "interaction_specification")

    if outputSpec is None and interactionSpec is None:
        raise ScrapingValidationError("Neither an Output nor an Interaction section was found in the problem statement.")

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
        "memory_limit_mb": memoryLimitMB,
        "statement_text": statementText,
        "input_specification": inputSpec,
        "output_specification": outputSpec,
        "interaction_specification": interactionSpec,
        "notes": notes
    }
    specs["statement_hash"] = computeStatementHash(specs)

    return specs, samples
