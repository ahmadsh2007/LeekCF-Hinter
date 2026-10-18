import time
from dataclasses import dataclass
import requests
from bs4 import BeautifulSoup
from src.services.scraper.errors import ScrapingValidationError, TransientScrapeError
from src.services.scraper.problemScraper import USER_AGENT
from src.workers.tutorial_finder.tutorialParser import (
    BASE_URL,
    findCsrfToken,
    findDynamicTutorials,
    findPostBody,
    findTutorialLinks,
    parseDynamicTutorial,
    splitBlogIntoSections,
)

REQUEST_TIMEOUT_SECONDS = 20
TUTORIAL_DATA_URL = f"{BASE_URL}/data/problemTutorial"
CHALLENGE_TITLE = "just a moment"

@dataclass(frozen=True)
class TutorialPost:
    url: str
    sections: dict[str, str]  # problem key -> text written out in the post
    dynamic: dict[str, str]   # problem key -> problem code to ask the data endpoint for
    csrfToken: str | None

class CodeforcesTutorialSource:
    """
    Reads contest pages and editorial posts the way a browser would (one session, so the cookies and CSRF token
    that the data endpoint wants are there). Anything that may work later raises TransientScrapeError;
    a page that does not exist raises ScrapingValidationError.
    """
    def __init__(self, session=None, delaySeconds: float = 2.0, sleep=time.sleep):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.delaySeconds = delaySeconds
        self.sleep = sleep
        self.requestCount = 0

    def throttle(self) -> None:
        if self.requestCount > 0 and self.delaySeconds > 0:
            self.sleep(self.delaySeconds)
        self.requestCount += 1

    def getPage(self, url: str) -> BeautifulSoup:
        self.throttle()
        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as e:
            raise TransientScrapeError(f"Network error ({type(e).__name__}) while fetching {url}: {e}") from e

        if response.status_code == 404:
            raise ScrapingValidationError(f"Page not found (HTTP 404): {url}")
        if response.status_code != 200:
            raise TransientScrapeError(f"HTTP {response.status_code} while fetching {url}")

        page = BeautifulSoup(response.text, "html.parser")
        if page.title and CHALLENGE_TITLE in page.title.get_text().lower():
            raise TransientScrapeError(f"Challenge page instead of the real page: {url}")
        return page

    def contestTutorialLinks(self, contestId: int) -> list[str]:
        url = f"{BASE_URL}/contest/{contestId}"
        page = self.getPage(url)
        if not page.select_one(".roundbox"):
            raise TransientScrapeError(f"Does not look like a contest page (maintenance page?): {url}")
        return findTutorialLinks(page)

    def fetchPost(self, url: str) -> TutorialPost:
        page = self.getPage(url)
        if findPostBody(page) is None:
            raise TransientScrapeError(f"No post body on the page: {url}")
        return TutorialPost(
            url=url,
            sections=splitBlogIntoSections(page),
            dynamic=findDynamicTutorials(page),
            csrfToken=findCsrfToken(page),
        )

    def fetchDynamicTutorial(self, post: TutorialPost, problemCode: str) -> str | None:
        """The tutorial text for one problem, or None when the site has none (or it is not public)."""
        if not post.csrfToken:
            raise TransientScrapeError(f"No CSRF token on {post.url}; cannot ask for the tutorial of {problemCode}")

        self.throttle()
        try:
            response = self.session.post(
                TUTORIAL_DATA_URL,
                data={"problemCode": problemCode, "csrf_token": post.csrfToken},
                headers={"X-Csrf-Token": post.csrfToken, "X-Requested-With": "XMLHttpRequest", "Referer": post.url},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            raise TransientScrapeError(f"Network error ({type(e).__name__}) while fetching the tutorial of {problemCode}: {e}") from e

        if response.status_code != 200:
            raise TransientScrapeError(f"HTTP {response.status_code} while fetching the tutorial of {problemCode}")
        try:
            answer = response.json()
        except ValueError as e:
            raise TransientScrapeError(f"The tutorial answer for {problemCode} was not JSON") from e

        if answer.get("success") != "true" or answer.get("public") == "false":
            return None
        return parseDynamicTutorial(answer.get("html", "")) or None
