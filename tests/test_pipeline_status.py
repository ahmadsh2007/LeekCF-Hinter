import unittest
from datetime import datetime, timedelta, timezone

from src.workers.status.pipelineStatus import STATUSES, collectSnapshot, findWarnings, renderReport
from tests.fakeSupabase import FakeSupabase

NOW = datetime(2026, 10, 20, 13, 0, tzinfo=timezone.utc)

def hoursAgo(hours: float) -> str:
    return (NOW - timedelta(hours=hours)).isoformat()

def problem(id, status, createdHoursAgo=100, error=None):
    return {"id": id, "stage_status": status, "created_at": hoursAgo(createdHoursAgo), "last_error": error}

def hint(id, problemId, model, hoursOld):
    return {"id": id, "problem_id": problemId, "llm_model_used": model, "created_at": hoursAgo(hoursOld)}

def healthyTables():
    return {
        "problems": [
            problem("1_A", "HINTS_GENERATED"), problem("1_B", "HINTS_GENERATED"), problem("2_A", "TUTORIAL_FOUND"),
            problem("3_A", "WAITING_FOR_TUTORIAL", createdHoursAgo=5), problem("4_A", "DUPLICATE"),
            problem("5_A", "FAILED", error="The statement is only published as a PDF, so there is nothing to scrape."),
            problem("5_B", "FAILED", error="The statement is only published as a PDF, so there is nothing to scrape."),
            problem("6_A", "FAILED", error="Required element '.input-specification' not found."),
        ],
        "hints": [hint(1, "1_A", "gemini-3.8-flash", 2), hint(2, "1_A", "gemini-3.8-flash", 2),
                  hint(3, "1_B", "gemini-3.5-flash-lite", 1), hint(4, "9_Z", "gemini-3.5-flash-lite", 80)],
        "api_usage_daily": [
            {"day": "2026-10-19", "client": "a", "route": "hints", "status": 200, "requests": 40},
            {"day": "2026-10-19", "client": "b", "route": "hints", "status": 404, "requests": 2},
            {"day": "2026-10-18", "client": "a", "route": "hints", "status": 200, "requests": 900},
        ],
    }


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = collectSnapshot(FakeSupabase(healthyTables()), NOW)

    def test_it_counts_the_problems_in_every_stage(self):
        self.assertEqual(self.snapshot.counts["HINTS_GENERATED"], 2)
        self.assertEqual(self.snapshot.counts["TUTORIAL_FOUND"], 1)
        self.assertEqual(self.snapshot.counts["FAILED"], 3)
        self.assertEqual(self.snapshot.counts["DISCOVERED"], 0)
        self.assertEqual(set(self.snapshot.counts), {status for status, _ in STATUSES})

    def test_it_counts_what_happened_in_the_last_24_hours_only(self):
        self.assertEqual(self.snapshot.newProblems, 1)            # 3_A
        self.assertEqual(self.snapshot.hintsWritten, 3)            # the 80-hour-old hint does not count
        self.assertEqual(self.snapshot.problemsWithNewHints, 2)
        self.assertEqual(self.snapshot.hintModels, {"gemini-3.8-flash": 2, "gemini-3.5-flash-lite": 1})

    def test_it_knows_when_the_latest_hint_was_written(self):
        self.assertEqual(self.snapshot.lastHintAt, NOW - timedelta(hours=1))

    def test_failed_problems_are_grouped_by_the_reason(self):
        self.assertEqual(self.snapshot.failedReasons, {
            "The statement is only published as a PDF, so there is nothing to scrape.": 2,
            "Required element '.input-specification' not found.": 1,
        })

    def test_it_sums_yesterdays_api_requests(self):
        self.assertEqual(self.snapshot.apiRequestsYesterday, 42)

    def test_without_saved_usage_statistics_the_api_figure_is_unknown(self):
        tables = healthyTables()
        tables["api_usage_daily"] = []
        self.assertIsNone(collectSnapshot(FakeSupabase(tables), NOW).apiRequestsYesterday)

    def test_an_empty_database_gives_zeros_and_no_last_hint(self):
        snapshot = collectSnapshot(FakeSupabase({"problems": [], "hints": [], "api_usage_daily": []}), NOW)
        self.assertEqual(sum(snapshot.counts.values()), 0)
        self.assertIsNone(snapshot.lastHintAt)
        self.assertEqual(snapshot.hintsWritten, 0)


class WarningTests(unittest.TestCase):
    def warnings(self, mutate=lambda tables: None):
        tables = healthyTables()
        mutate(tables)
        return findWarnings(collectSnapshot(FakeSupabase(tables), NOW))

    def test_a_healthy_day_has_no_warnings(self):
        self.assertEqual(self.warnings(), [])

    def test_hints_waiting_but_none_written_for_a_day_is_a_stall(self):
        found = self.warnings(lambda t: t.update(hints=[hint(4, "9_Z", "gemini-3.5-flash-lite", 80)]))
        self.assertEqual(len(found), 1)
        self.assertIn("No hint was written in the last 24 hours", found[0])
        self.assertIn("1 problem", found[0])

    def test_nothing_waiting_for_hints_means_no_stall_even_when_no_hint_was_written(self):
        def finished(tables):
            tables["hints"] = []
            tables["problems"] = [problem("1_A", "HINTS_GENERATED"), problem("3_A", "WAITING_FOR_TUTORIAL")]
        self.assertEqual(self.warnings(finished), [])

    def test_statements_waiting_more_than_two_days_to_be_scraped_are_a_warning(self):
        found = self.warnings(lambda t: t["problems"].extend([problem("7_A", "DISCOVERED", createdHoursAgo=60), problem("7_B", "DISCOVERED", createdHoursAgo=3)]))
        self.assertEqual(len(found), 1)
        self.assertIn("1 problem", found[0])
        self.assertIn("scraped", found[0])

    def test_new_problems_that_are_only_hours_old_are_not_a_warning(self):
        self.assertEqual(self.warnings(lambda t: t["problems"].append(problem("7_B", "DISCOVERED", createdHoursAgo=3))), [])


class ReportTests(unittest.TestCase):
    def render(self, mutate=lambda tables: None):
        tables = healthyTables()
        mutate(tables)
        snapshot = collectSnapshot(FakeSupabase(tables), NOW)
        return renderReport(snapshot, findWarnings(snapshot))

    def test_it_shows_every_stage_the_last_day_and_the_failures(self):
        text = self.render()
        self.assertIn("2026-10-20 13:00 UTC", text)
        self.assertIn("8 problems", text)
        self.assertIn("- 2 hints ready", text)
        self.assertIn("3 hints written for 2 problems", text)
        self.assertIn("gemini-3.8-flash: 2", text)
        self.assertIn("1 hour ago", text)
        self.assertIn("2 x The statement is only published as a PDF", text)
        self.assertIn("42 API requests yesterday", text)
        self.assertIn("No warnings.", text)

    def test_warnings_are_listed_prominently(self):
        text = self.render(lambda t: t.update(hints=[]))
        self.assertIn("WARNING: No hint was written in the last 24 hours", text)
        self.assertNotIn("No warnings.", text)
        self.assertIn("No hint has been written yet", text)

    def test_an_unknown_api_figure_is_said_so(self):
        text = self.render(lambda t: t.update(api_usage_daily=[]))
        self.assertIn("no saved API statistics for yesterday", text)


if __name__ == "__main__":
    unittest.main()
