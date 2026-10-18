import unittest

import requests

from src.services.scraper.errors import ScrapingValidationError, TransientScrapeError
from src.workers.tutorial_finder.tutorialSource import CodeforcesTutorialSource, TutorialPost

CONTEST_PAGE = ('<html><head><title>Dashboard</title></head><body><div class="roundbox"><div class="caption">→ Contest materials</div>'
                '<ul><li><a href="/blog/entry/7">Tutorial (en)</a></li></ul></div></body></html>')
LONG = " This explanation is long enough to count as real content for the section filter."
BLOG_PAGE = ('<html><head><title>Editorial</title><meta name="X-Csrf-Token" content="tok123"/></head><body>'
             '<div class="topic"><div class="content"><div class="ttypography">'
             '<p><a href="/contest/5/problem/A">5A - Foo</a></p>' + f"<p>Static text.{LONG}</p>"
             '<p><a href="/contest/5/problem/B">5B - Bar</a></p><div class="problemTutorial" problemcode="5B">Tutorial is loading...</div>'
             '</div></div></div></body></html>')


class FakeResponse:
    def __init__(self, status=200, text="", jsonData=None, badJson=False):
        self.status_code = status
        self.text = text
        self.jsonData = jsonData
        self.badJson = badJson

    def json(self):
        if self.badJson:
            raise ValueError("not json")
        return self.jsonData


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.headers = {}

    def next(self):
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def get(self, url, timeout=None):
        self.requests.append({"method": "GET", "url": url})
        return self.next()

    def post(self, url, data=None, headers=None, timeout=None):
        self.requests.append({"method": "POST", "url": url, "data": data, "headers": headers})
        return self.next()


def sourceWith(*responses, delay=0.0):
    sleeps = []
    session = FakeSession(*responses)
    return CodeforcesTutorialSource(session=session, delaySeconds=delay, sleep=sleeps.append), session, sleeps


class ContestLinkTests(unittest.TestCase):
    def test_returns_the_tutorial_links_of_the_contest_page(self):
        source, session, _ = sourceWith(FakeResponse(200, CONTEST_PAGE))
        self.assertEqual(source.contestTutorialLinks(5), ["https://codeforces.com/blog/entry/7"])
        self.assertEqual(session.requests[0]["url"], "https://codeforces.com/contest/5")

    def test_network_error_is_transient(self):
        source, _, _ = sourceWith(requests.ConnectionError("down"))
        with self.assertRaises(TransientScrapeError):
            source.contestTutorialLinks(5)

    def test_block_or_rate_limit_is_transient(self):
        for status in (403, 429, 503):
            source, _, _ = sourceWith(FakeResponse(status, "x"))
            with self.assertRaises(TransientScrapeError, msg=str(status)):
                source.contestTutorialLinks(5)

    def test_missing_contest_is_a_permanent_miss(self):
        source, _, _ = sourceWith(FakeResponse(404, "x"))
        with self.assertRaises(ScrapingValidationError):
            source.contestTutorialLinks(5)

    def test_a_challenge_page_with_status_200_is_transient(self):
        # even with a contest-looking body, the challenge title decides
        challenge = CONTEST_PAGE.replace("<title>Dashboard</title>", "<title>Just a moment...</title>")
        source, _, _ = sourceWith(FakeResponse(200, challenge))
        with self.assertRaises(TransientScrapeError):
            source.contestTutorialLinks(5)

    def test_a_page_that_is_not_a_contest_page_is_transient(self):
        source, _, _ = sourceWith(FakeResponse(200, "<html><body>maintenance</body></html>"))
        with self.assertRaises(TransientScrapeError):
            source.contestTutorialLinks(5)


class BlogTests(unittest.TestCase):
    def test_reads_sections_placeholders_and_the_csrf_token(self):
        source, session, _ = sourceWith(FakeResponse(200, BLOG_PAGE))
        post = source.fetchPost("https://codeforces.com/blog/entry/7")
        self.assertEqual(post.url, "https://codeforces.com/blog/entry/7")
        self.assertEqual(post.sections, {"5_A": f"Static text.{LONG}"})
        self.assertEqual(post.dynamic, {"5_B": "5B"})
        self.assertEqual(post.csrfToken, "tok123")

    def test_a_blog_page_without_a_post_is_transient(self):
        source, _, _ = sourceWith(FakeResponse(200, "<html><body>nothing here</body></html>"))
        with self.assertRaises(TransientScrapeError):
            source.fetchPost("https://codeforces.com/blog/entry/7")

    def test_a_missing_post_is_a_permanent_miss(self):
        source, _, _ = sourceWith(FakeResponse(404, "x"))
        with self.assertRaises(ScrapingValidationError):
            source.fetchPost("https://codeforces.com/blog/entry/7")


class DynamicTutorialTests(unittest.TestCase):
    POST = TutorialPost(url="https://codeforces.com/blog/entry/7", sections={}, dynamic={"5_B": "5B"}, csrfToken="tok123")
    OK = {"success": "true", "public": "true", "html": "<h3>5B - Bar</h3><div class=\"ttypography\"><p>Dynamic text.</p></div>"}

    def test_posts_the_problem_code_the_way_the_site_does(self):
        source, session, _ = sourceWith(FakeResponse(200, "", self.OK))
        self.assertEqual(source.fetchDynamicTutorial(self.POST, "5B"), "Dynamic text.")
        request = session.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["url"], "https://codeforces.com/data/problemTutorial")
        self.assertEqual(request["data"], {"problemCode": "5B", "csrf_token": "tok123"})
        self.assertEqual(request["headers"]["X-Csrf-Token"], "tok123")
        self.assertEqual(request["headers"]["Referer"], self.POST.url)

    def test_a_tutorial_that_is_not_public_is_not_used(self):
        source, _, _ = sourceWith(FakeResponse(200, "", {**self.OK, "public": "false"}))
        self.assertIsNone(source.fetchDynamicTutorial(self.POST, "5B"))

    def test_an_unsuccessful_answer_means_no_tutorial(self):
        source, _, _ = sourceWith(FakeResponse(200, "", {"success": "false"}))
        self.assertIsNone(source.fetchDynamicTutorial(self.POST, "5B"))

    def test_an_empty_tutorial_means_no_tutorial(self):
        source, _, _ = sourceWith(FakeResponse(200, "", {**self.OK, "html": "<h3>5B - Bar</h3>"}))
        self.assertIsNone(source.fetchDynamicTutorial(self.POST, "5B"))

    def test_non_200_and_bad_json_are_transient(self):
        for response in (FakeResponse(403, "x"), FakeResponse(200, "x", badJson=True), requests.Timeout("slow")):
            source, _, _ = sourceWith(response)
            with self.assertRaises(TransientScrapeError):
                source.fetchDynamicTutorial(self.POST, "5B")

    def test_without_a_csrf_token_nothing_is_sent(self):
        source, session, _ = sourceWith()
        post = TutorialPost(url=self.POST.url, sections={}, dynamic={"5_B": "5B"}, csrfToken=None)
        with self.assertRaises(TransientScrapeError):
            source.fetchDynamicTutorial(post, "5B")
        self.assertEqual(session.requests, [])


class ThrottleTests(unittest.TestCase):
    def test_waits_between_requests_but_not_before_the_first(self):
        source, _, sleeps = sourceWith(FakeResponse(200, CONTEST_PAGE), FakeResponse(200, CONTEST_PAGE), FakeResponse(200, CONTEST_PAGE), delay=2.0)
        source.contestTutorialLinks(1)
        self.assertEqual(sleeps, [])
        source.contestTutorialLinks(2)
        source.contestTutorialLinks(3)
        self.assertEqual(sleeps, [2.0, 2.0])


if __name__ == "__main__":
    unittest.main()
