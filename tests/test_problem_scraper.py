import unittest
from unittest.mock import Mock, patch

import requests

from src.services.scraper.errors import ScrapingValidationError, TransientScrapeError
from src.services.scraper.problemScraper import scrapeProblemPage

PROBLEM_PAGE = '<html><body><div class="problem-statement"><div class="header"></div></div></body></html>'


def fakeResponse(statusCode: int, text: str = "", contentType: str = "text/html;charset=UTF-8") -> Mock:
    return Mock(status_code=statusCode, text=text, headers={"Content-Type": contentType})


@patch("src.services.scraper.problemScraper.requests.get")
class ScrapeProblemPageTests(unittest.TestCase):
    def test_ok_page_with_a_statement_is_returned_as_soup(self, mockGet):
        mockGet.return_value = fakeResponse(200, PROBLEM_PAGE)
        soup = scrapeProblemPage(1800, "A")
        self.assertIsNotNone(soup.select_one(".problem-statement"))

    def test_requests_the_problemset_url_with_a_timeout_and_a_browser_user_agent(self, mockGet):
        mockGet.return_value = fakeResponse(200, PROBLEM_PAGE)
        scrapeProblemPage(1800, "B1")
        args, kwargs = mockGet.call_args
        self.assertEqual(args[0], "https://codeforces.com/problemset/problem/1800/B1")
        self.assertEqual(kwargs["timeout"], 10)
        self.assertTrue(kwargs["headers"]["User-Agent"].startswith("Mozilla/5.0"))

    def test_ok_page_without_a_statement_is_transient_because_it_may_be_a_challenge_page(self, mockGet):
        mockGet.return_value = fakeResponse(200, "<html><body>Just a moment...</body></html>")
        with self.assertRaises(TransientScrapeError) as raised:
            scrapeProblemPage(1800, "A")
        self.assertIn("problem statement", str(raised.exception))

    def test_a_statement_published_only_as_a_pdf_is_permanent(self, mockGet):
        # Some contests (e.g. 2073, an ICPC mirror) answer the problem URL with the statement as a PDF file.
        mockGet.return_value = fakeResponse(200, "%PDF-1.5 binary", contentType="application/pdf;charset=UTF-8")
        with self.assertRaises(ScrapingValidationError) as raised:
            scrapeProblemPage(2073, "K")
        self.assertIn("PDF", str(raised.exception))

    def test_404_is_permanent(self, mockGet):
        mockGet.return_value = fakeResponse(404)
        with self.assertRaises(ScrapingValidationError) as raised:
            scrapeProblemPage(1800, "A")
        self.assertIn("404", str(raised.exception))

    def test_blocks_rate_limits_and_server_errors_are_transient(self, mockGet):
        for statusCode in (403, 429, 500, 502, 503):
            with self.subTest(statusCode=statusCode):
                mockGet.return_value = fakeResponse(statusCode)
                with self.assertRaises(TransientScrapeError) as raised:
                    scrapeProblemPage(1800, "A")
                self.assertIn(str(statusCode), str(raised.exception))

    def test_network_errors_are_transient(self, mockGet):
        for error in (requests.ConnectionError("down"), requests.Timeout("slow")):
            with self.subTest(error=type(error).__name__):
                mockGet.side_effect = error
                with self.assertRaises(TransientScrapeError) as raised:
                    scrapeProblemPage(1800, "A")
                self.assertIn(type(error).__name__, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
