import unittest
from datetime import datetime, timedelta, timezone

from src.services.scraper.errors import ScrapingValidationError, TransientScrapeError
from src.workers.tutorial_finder.findTutorials import (
    DUPLICATE_FETCH_CHUNK_SIZE,
    MAX_CONSECUTIVE_TRANSIENT_FAILURES,
    NO_TUTORIAL_NOTE,
    run,
)
from src.workers.tutorial_finder.tutorialSource import TutorialPost
from tests.fakeSupabase import FakeSupabase

LONG = " This explanation is long enough to be a tutorial."


NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
LONG_AGO = (NOW - timedelta(days=30)).isoformat()

def waiting(problemId, contestId, lastError=None, updatedAt=LONG_AGO):
    return {"id": problemId, "contest_id": contestId, "stage_status": "WAITING_FOR_TUTORIAL", "canonical_problem_id": None,
            "last_error": lastError, "updated_at": updatedAt}

def duplicate(problemId, contestId, canonicalId):
    return {"id": problemId, "contest_id": contestId, "stage_status": "DUPLICATE", "canonical_problem_id": canonicalId,
            "last_error": None, "updated_at": LONG_AGO}

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
    """Ids moved on to TUTORIAL_FOUND (the "checked, nothing yet" notes are a different kind of update)."""
    return [i for call in client.writes("problems", "update") if call.payload.get("stage_status") == "TUTORIAL_FOUND"
            for i in call.inFilters[0][1]]


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
        self.assertEqual(update.payload, {"stage_status": "TUTORIAL_FOUND", "last_error": None, "updated_at": "now()"})
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

    def test_contest_without_a_tutorial_yet_keeps_its_problems_waiting(self):
        client = FakeSupabase({"problems": [waiting("1_A", 1)]})
        result = run(client, FakeSource(links={1: []}))
        self.assertEqual(client.writes("tutorials", "upsert"), [])
        self.assertEqual(promotedIds(client), [])
        self.assertEqual([u.payload["last_error"] for u in client.writes("problems", "update")], [NO_TUTORIAL_NOTE])
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


def noteUpdates(client):
    return [u for u in client.writes("problems", "update") if u.payload.get("last_error") == NO_TUTORIAL_NOTE]

def checked(problemId, contestId, hoursAgo):
    return waiting(problemId, contestId, lastError=NO_TUTORIAL_NOTE, updatedAt=(NOW - timedelta(hours=hoursAgo)).isoformat())


class RecheckTests(unittest.TestCase):
    """A contest with no tutorial yet is looked at again only after a while, not on every run."""

    def test_a_contest_without_a_tutorial_is_noted_so_it_is_not_asked_again_at_once(self):
        client = FakeSupabase({"problems": [waiting("1_A", 1), waiting("1_B", 1)]})
        run(client, FakeSource(links={1: []}), now=NOW)
        update = noteUpdates(client)[0]
        self.assertEqual(update.payload, {"last_error": NO_TUTORIAL_NOTE, "updated_at": "now()"})
        self.assertEqual(update.inFilters, [("id", ["1_A", "1_B"])])
        self.assertEqual(update.eqFilters, [("stage_status", "WAITING_FOR_TUTORIAL")])

    def test_a_post_that_does_not_cover_a_problem_notes_that_problem_too(self):
        client = FakeSupabase({"problems": [waiting("1_A", 1), waiting("1_B", 1)]})
        run(client, FakeSource(links={1: ["u"]}, posts={"u": post("u", sections={"1_A": f"a{LONG}"})}), now=NOW)
        self.assertEqual(noteUpdates(client)[0].inFilters, [("id", ["1_B"])])

    def test_problems_checked_recently_are_skipped_without_any_request(self):
        client = FakeSupabase({"problems": [checked("1_A", 1, hoursAgo=3)]})
        source = FakeSource(links={1: ["u"]}, posts={"u": post("u", sections={"1_A": f"a{LONG}"})})
        result = run(client, source, now=NOW)
        self.assertEqual(source.calls, [])
        self.assertEqual(result["skipped_recently_checked"], 1)

    def test_they_are_looked_at_again_after_the_wait(self):
        client = FakeSupabase({"problems": [checked("1_A", 1, hoursAgo=25)]})
        source = FakeSource(links={1: ["u"]}, posts={"u": post("u", sections={"1_A": f"a{LONG}"})})
        result = run(client, source, now=NOW)
        self.assertEqual(result["found"], 1)
        self.assertEqual(result["skipped_recently_checked"], 0)

    def test_the_wait_can_be_changed_or_switched_off(self):
        client = FakeSupabase({"problems": [checked("1_A", 1, hoursAgo=3)]})
        self.assertEqual(run(client, FakeSource(links={1: []}), now=NOW, recheckAfterHours=2)["no_tutorial_yet"], 1)
        client = FakeSupabase({"problems": [checked("1_A", 1, hoursAgo=0.1)]})
        self.assertEqual(run(client, FakeSource(links={1: []}), now=NOW, recheckAfterHours=0)["no_tutorial_yet"], 1)

    def test_only_the_note_makes_a_problem_skippable_not_other_errors_or_fresh_updates(self):
        other = waiting("1_A", 1, lastError="Unexpected error: boom", updatedAt=(NOW - timedelta(hours=1)).isoformat())
        fresh = waiting("1_B", 1, lastError=None, updatedAt=(NOW - timedelta(minutes=5)).isoformat())
        source = FakeSource(links={1: []})
        result = run(FakeSupabase({"problems": [other, fresh]}), source, now=NOW)
        self.assertEqual(result["skipped_recently_checked"], 0)
        self.assertEqual(result["no_tutorial_yet"], 1)

    def test_a_contest_that_could_not_be_checked_is_not_noted(self):
        client = FakeSupabase({"problems": [waiting("1_A", 1)]})
        run(client, FakeSource(links={1: TransientScrapeError("HTTP 403")}), now=NOW)
        self.assertEqual(noteUpdates(client), [])

    def test_a_post_that_failed_to_load_does_not_note_its_problems(self):
        client = FakeSupabase({"problems": [waiting("1_A", 1)]})
        run(client, FakeSource(links={1: ["u"]}, posts={"u": TransientScrapeError("HTTP 429")}), now=NOW)
        self.assertEqual(noteUpdates(client), [])

    def test_a_found_tutorial_clears_an_earlier_note(self):
        client = FakeSupabase({"problems": [checked("1_A", 1, hoursAgo=30)]})
        run(client, FakeSource(links={1: ["u"]}, posts={"u": post("u", sections={"1_A": f"a{LONG}"})}), now=NOW)
        self.assertIsNone(client.writes("problems", "update")[-1].payload["last_error"])

    def test_old_stuck_contests_do_not_starve_the_ones_behind_them(self):
        # 3 stuck contests were checked an hour ago; with a limit of 3 contests the run must reach the older, fresh ones.
        stuck = [checked(f"{c}_A", c, hoursAgo=1) for c in (9, 8, 7)]
        fresh = [waiting("2_A", 2), waiting("1_A", 1)]
        source = FakeSource(links={2: ["u"], 1: ["u"]}, posts={"u": post("u", sections={"2_A": f"a{LONG}", "1_A": f"b{LONG}"})})
        result = run(FakeSupabase({"problems": stuck + fresh}), source, contestLimit=3, now=NOW)
        self.assertEqual(result["found"], 2)


class DatabaseTroubleTests(unittest.TestCase):
    def test_a_blip_while_saving_is_retried_and_the_tutorial_is_kept(self):
        client = FakeSupabase({"problems": [waiting("1_A", 1)]}, networkFailures={("tutorials", "upsert"): 2})
        source = FakeSource(links={1: ["u"]}, posts={"u": post("u", sections={"1_A": f"a{LONG}"})})
        result = run(client, source, sleep=lambda seconds: None)
        self.assertEqual(result["found"], 1)
        self.assertEqual(promotedIds(client), ["1_A"])

    def test_a_database_that_stays_down_skips_that_contest_and_carries_on(self):
        client = FakeSupabase({"problems": [waiting("1_A", 1), waiting("2_A", 2)]}, networkFailures={("tutorials", "upsert"): 4})
        source = FakeSource(links={1: ["u1"], 2: ["u2"]}, posts={"u1": post("u1", sections={"1_A": f"a{LONG}"}), "u2": post("u2", sections={"2_A": f"b{LONG}"})})
        result = run(client, source, sleep=lambda seconds: None)
        # contest 2 is visited first (newest first) and loses its save; contest 1 then saves normally
        self.assertEqual(promotedIds(client), ["1_A"])
        self.assertEqual(result["transient_failures"], 1)
        self.assertEqual(result["found"], 1)  # the contest whose save failed is not counted as done

    def test_a_blip_while_loading_the_waiting_problems_is_retried(self):
        client = FakeSupabase({"problems": [waiting("1_A", 1)]}, networkFailures={("problems", "select"): 1})
        source = FakeSource(links={1: []})
        self.assertEqual(run(client, source, sleep=lambda seconds: None)["no_tutorial_yet"], 1)


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
