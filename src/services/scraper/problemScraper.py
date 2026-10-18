import requests
from bs4 import BeautifulSoup
from src.services.scraper.errors import ScrapingValidationError, TransientScrapeError

# Codeforces tends to reject the default python-requests agent.
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

def scrapeProblemPage(contest_id: int, index: str) -> BeautifulSoup:
    """
    Returns the parsed problem page.
    Raises TransientScrapeError when retrying later may work (network error, block, rate limit, server error,
    or a 200 page with no problem statement such as a challenge page), and ScrapingValidationError when the
    page does not exist (404).
    """
    url = f"https://codeforces.com/problemset/problem/{contest_id}/{index}"
    print(f"Scraping: {url}")

    try:
        response = requests.get(url, timeout=10, headers={"User-Agent": USER_AGENT})
    except requests.RequestException as e:
        raise TransientScrapeError(f"Network error ({type(e).__name__}) while fetching {url}: {e}") from e

    if response.status_code == 404:
        raise ScrapingValidationError(f"Problem page not found (HTTP 404): {url}")
    if response.status_code != 200:
        raise TransientScrapeError(f"HTTP {response.status_code} while fetching {url}")

    soup = BeautifulSoup(response.text, 'html.parser')
    if not soup.select_one(".problem-statement"):
        raise TransientScrapeError(f"No problem statement on the page (challenge or maintenance page?): {url}")
    return soup
