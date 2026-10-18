import unittest

from src.services.scraper.errors import ScrapingValidationError, TransientScrapeError
from src.workers.tutorial_finder.findTutorials import (
    DUPLICATE_FETCH_CHUNK_SIZE,
    MAX_CONSECUTIVE_TRANSIENT_FAILURES,
    run,
)
from src.workers.tutorial_finder.tutorialSource import TutorialPost
from tests.fakeSupabase import FakeSupabase

LONG = " This explanation is long enough to be a tutorial."


def waiting(problemId, contestId):
    return {"id": problemId, "contest_id": contestId, "stage_status": "WAITING_FOR_TUTORIAL", "canonical_problem_id": None}

def duplicate(problemId, contestId, canonicalId):
    return {"id": problemId, "contest_id": contestId, "stage_status": "DUPLICATE", "canonical_problem_id": canonicalId}

def post(url, sections=None, dynamic=None):
    return TutorialPost(url=url, sections=sections or {}, dynamic=dynamic or {}, csrfToken="tok")


class FakeSource:
    def __init__(self, links=None, posts=None, dynamic=None):
        self.links = links or {}      # contest id -> list of urls, or an exception to raise
        self.posts = posts or {}      # url -> TutorialPost, or an exception
        self.dynamicTexts = dynamic or {}  # problem code -> text, None, or an exception
        self.calls = []

    def contestTutorialLinks(self, contestId):
        self.calls.append(("links", contestId))
        return self.answer(self.links.get(contestId, []))

    def fetchPost(self, url):
        self.calls.append(("post", url))
        return self.answer(self.posts[url])

    def fetchDynamicTutorial(self, tutorialPost, problemCode):
        self.calls.append(("dynamic", problemCode))
        return self.answer(self.dynamicTexts.get(problemCode))

    @staticmethod
    def answer(value):
        if isinstance(value, Exception):
            raise value
        return value

    def callsOfKind(self, kind):
        return [call for call in self.calls if call[0] == kind]


def tutorialRows(client):
    return [row for call in client.writes("tutorials", "upsert") for row in call.payload]

def promotedIds(client):
    return [i for call in client.writes("problems", "update") for i in call.inFilters[0][1]]


class SavingTests(unittest.TestCase):
    def test_a_static_section_is_saved_and_the_problem_moves_on(self):
        client = FakeSupabase({"problems": [waiting("1_A", 1)]})
        source = FakeSource(links={1: ["u1"]}, posts={"u1": post("u1", sections={"1_A": f"Idea.{LONG}"})})

        result = run(client, source)

        upserts = client.writes("tutorials", "upsert")
        self.assertEqual(len(upserts), 1)
        self.assertEqual(upserts[0].onConflict, "problem_id")
        self.assertEqual(upserts[0].payload, [{
            "problem_id": "1_A", "contest_id": 1, "source_url": "u1", "raw_content": f"Idea.{LONG}",
            "author": None, "scraped_at": "now()",
        }])
        update = client.writes("problems", "update")[0]
        self.assertEqual(update.payload["stage_status"], "TUTORIAL_FOUND")
        self.assertEqual(update.payload["updated_at"], "now()")
        self.assertEqual(update.eqFilters, [("stage_status", "WAITING_FOR_TUTORIAL")])
        self.assertEqual(update.inFilters, [("id", ["1_A"])])
        self.assertEqual(result["found"], 1)

    def test_the_tutorial_is_stored_before_the_status_changes(self):
        client = FakeSupabase({"problems": [waiting("1_A", 1)]})
        run(client, FakeSource(links={1: ["u1"]}, posts={"u1": post("u1", sections={"1_A": f"x{LONG}"})}))
        tables = [call.tableName for call in client.calls if call.operation in ("upsert", "update")]
        self.assertEqual(tables, ["tutorials", "problems"])

    def test_a_dynamic_tutorial_is_used_when_the_post_has_a_placeholder(self):
        client = FakeSupabase({"problems": [waiting("1_A", 1)]})
        source = FakeSource(links={1: ["u1"]}, posts={"u1": post("u1", dynamic={"1_A": "1A"})}, dynamic={"1A": f"Loaded text.{LONG}"})
        run(client, source)
        self.assertEqual(tutorialRows(client)[0]["raw_content"], f"Loaded text.{LONG}")

    def test_dynamic_wins_over_static_but_static_is_the_fallback(self):
        sections = {"1_A": f"Static A.{LONG}", "1_B": f"Static B.{LONG}"}
        client = FakeSupabase({"problems": [waiting("1_A", 1), waiting("1_B", 1)]})
        source = FakeSource(
            links={1: ["u1"]},
            posts={"u1": post("u1", sections=sections, dynamic={"1_A": "1A", "1_B": "1B"})},
            dynamic={"1A": f"Dynamic A.{LONG}", "1B": None},
        )
        run(client, source)
        texts = {row["problem_id"]: row["raw_content"] for row in tutorialRows(client)}
        self.assertEqual(texts, {"1_A": f"Dynamic A.{LONG}", "1_B": f"Static B.{LONG}"})

    def test_a_problem_the_post_does_not_cover_stays_waiting(self):
        client = FakeSupabase({"problems": [waiting("1_A", 1), waiting("1_B", 1)]})
        run(client, FakeSource(links={1: ["u1"]}, posts={"u1": post("u1", sections={"1_A": f"x{LONG}"})}))
        self.assertEqual([row["problem_id"] for row in tutorialRows(client)], ["1_A"])
        self.assertEqual(promotedIds(client), ["1_A"])

    def test_contest_without_a_tutorial_yet_changes_nothing(self):
        client = FakeSupabase({"problems": [waiting("1_A", 1)]})
        result = run(client, FakeSource(links={1: []}))
        self.assertEqual(client.writes("tutorials", "upsert"), [])
        self.assertEqual(client.writes("problems", "update"), [])
        self.assertEqual(result["no_tutorial_yet"], 1)

    def test_nothing_waiting_means_no_requests(self):
        source = FakeSource()
        result = run(FakeSupabase({"problems": [{"id": "1_A", "contest_id": 1, "stage_status": "DISCOVERED", "canonical_problem_id": None}]}), source)
        self.assertEqual(source.calls, [])
        self.assertEqual(result["found"], 0)


class SharedPostAndDuplicateTests(unittest.TestCase):
    def test_one_post_for_two_contests_is_fetched_once_and_the_second_contest_is_skipped(self):
        client = FakeSupabase({"problems": [waiting("1_A", 1), waiting("2_A", 2)]})
        source = FakeSource(
            links={1: ["u"], 2: ["u"]},
            posts={"u": post("u", sections={"1_A": f"a{LONG}", "2_A": f"b{LONG}"})},
        )
        run(client, source)
        self.assertEqual(len(source.callsOfKind("post")), 1)
        self.assertEqual(sorted(row["problem_id"] for row in tutorialRows(client)), ["1_A", "2_A"])
        self.assertEqual(len(source.callsOfKind("links")), 1)

    def test_a_duplicate_found_in_its_own_contests_post_serves_the_canonical(self):
        # 1943_A is canonical; the post only has a section for its twin 1944_C.
        client = FakeSupabase({"problems": [waiting("1943_A", 1943), duplicate("1944_C", 1944, "1943_A")]})
        source = FakeSource(links={1943: [], 1944: ["u"]}, posts={"u": post("u", sections={"1944_C": f"twin text{LONG}"})})

        run(client, source)

        self.assertEqual(tutorialRows(client), [{
            "problem_id": "1943_A", "contest_id": 1943, "source_url": "u",
            "raw_content": f"twin text{LONG}", "author": None, "scraped_at": "now()",
        }])
        self.assertEqual(promotedIds(client), ["1943_A"])

    def test_the_canonicals_own_key_is_preferred_over_a_twins(self):
        client = FakeSupabase({"problems": [waiting("1943_A", 1943), duplicate("1944_C", 1944, "1943_A")]})
        source = FakeSource(links={1943: ["u"], 1944: ["u"]}, posts={"u": post("u", sections={"1943_A": f"own{LONG}", "1944_C": f"twin{LONG}"})})
        run(client, source)
        self.assertEqual(tutorialRows(client)[0]["raw_content"], f"own{LONG}")
        # the newest contest (1944) was visited first and already settled the problem, so 1943's page is never fetched
        self.assertEqual(source.callsOfKind("links"), [("links", 1944)])

    def test_duplicates_are_looked_up_by_status_and_canonical_in_chunks(self):
        rows = [waiting(f"{i}_A", i) for i in range(1, DUPLICATE_FETCH_CHUNK_SIZE + 6)]
        client = FakeSupabase({"problems": rows})
        run(client, FakeSource())
        lookups = [call for call in client.selects("problems") if call.inFilters and call.inFilters[0][0] == "canonical_problem_id"]
        self.assertEqual([len(call.inFilters[0][1]) for call in lookups], [DUPLICATE_FETCH_CHUNK_SIZE, 5])
        self.assertTrue(all(call.eqFilters == [("stage_status", "DUPLICATE")] for call in lookups))


class FailureHandlingTests(unittest.TestCase):
    def test_a_transient_failure_skips_that_contest_and_carries_on(self):
        client = FakeSupabase({"problems": [waiting("1_A", 1), waiting("2_A", 2)]})
        source = FakeSource(links={2: TransientScrapeError("HTTP 403"), 1: ["u"]}, posts={"u": post("u", sections={"1_A": f"a{LONG}"})})
        result = run(client, source)
        self.assertEqual(promotedIds(client), ["1_A"])
        self.assertEqual(result["transient_failures"], 1)

    def test_a_missing_contest_page_is_not_a_failure_streak(self):
        client = FakeSupabase({"problems": [waiting(f"{i}_A", i) for i in range(1, 12)]})
        source = FakeSource(links={i: ScrapingValidationError("404") for i in range(1, 12)})
        result = run(client, source)
        self.assertEqual(result["not_found"], 11)
        self.assertEqual(len(source.callsOfKind("links")), 11)

    def test_the_run_stops_after_too_many_failures_in_a_row(self):
        count = MAX_CONSECUTIVE_TRANSIENT_FAILURES + 4
        client = FakeSupabase({"problems": [waiting(f"{i}_A", i) for i in range(1, count + 1)]})
        source = FakeSource(links={i: TransientScrapeError("HTTP 403") for i in range(1, count + 1)})
        result = run(client, source)
        self.assertEqual(len(source.callsOfKind("links")), MAX_CONSECUTIVE_TRANSIENT_FAILURES)
        self.assertEqual(result["transient_failures"], MAX_CONSECUTIVE_TRANSIENT_FAILURES)

    def test_a_success_resets_the_streak(self):
        # newest contest first: 9..6 fail, 5 works, 4..1 fail -> never five in a row
        client = FakeSupabase({"problems": [waiting(f"{i}_A", i) for i in range(1, 10)]})
        links = {i: TransientScrapeError("HTTP 403") for i in range(1, 10)}
        links[5] = []
        source = FakeSource(links=links)
        run(client, source)
        self.assertEqual(len(source.callsOfKind("links")), 9)

    def test_one_failing_dynamic_fetch_keeps_the_other_problems_of_the_post(self):
        client = FakeSupabase({"problems": [waiting("1_A", 1), waiting("1_B", 1)]})
        source = FakeSource(
            links={1: ["u"]},
            posts={"u": post("u", dynamic={"1_A": "1A", "1_B": "1B"})},
            dynamic={"1A": TransientScrapeError("HTTP 429"), "1B": f"B text.{LONG}"},
        )
        result = run(client, source)
        self.assertEqual([row["problem_id"] for row in tutorialRows(client)], ["1_B"])
        self.assertEqual(result["transient_failures"], 1)

    def test_results_of_earlier_contests_survive_a_crash_in_a_later_one(self):
        client = FakeSupabase({"problems": [waiting("1_A", 1), waiting("2_A", 2)]})
        source = FakeSource(links={2: ["u"], 1: RuntimeError("boom")}, posts={"u": post("u", sections={"2_A": f"a{LONG}"})})
        with self.assertRaises(RuntimeError):
            run(client, source)
        self.assertEqual(promotedIds(client), ["2_A"])

    def test_contest_limit_bounds_the_run(self):
        client = FakeSupabase({"problems": [waiting(f"{i}_A", i) for i in range(1, 8)]})
        source = FakeSource()
        run(client, source, contestLimit=3)
        self.assertEqual(source.callsOfKind("links"), [("links", 7), ("links", 6), ("links", 5)])


if __name__ == "__main__":
    unittest.main()
