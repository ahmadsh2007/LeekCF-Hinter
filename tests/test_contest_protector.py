import unittest
from datetime import datetime, timedelta, timezone

from src.workers.contest_monitor.contestProtector import (
    COOLDOWN,
    PROMOTE_CHUNK_SIZE,
    isContestOver,
    planPromotions,
    run,
)
from tests.fakeSupabase import FakeSupabase

START = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
DURATION = 7200
END = START + timedelta(seconds=DURATION)


class IsContestOverTests(unittest.TestCase):
    def test_finished_and_two_hours_after_the_end_is_over(self):
        self.assertTrue(isContestOver("FINISHED", START, DURATION, END + COOLDOWN + timedelta(minutes=1)))

    def test_exactly_at_the_cooldown_boundary_is_over(self):
        self.assertTrue(isContestOver("FINISHED", START, DURATION, END + COOLDOWN))

    def test_one_minute_before_the_cooldown_ends_is_not_over(self):
        self.assertFalse(isContestOver("FINISHED", START, DURATION, END + COOLDOWN - timedelta(minutes=1)))

    def test_cooldown_is_two_hours(self):
        self.assertEqual(COOLDOWN, timedelta(hours=2))

    def test_a_phase_that_is_not_finished_is_never_over_however_late_it_is(self):
        longAfter = END + timedelta(days=30)
        for phase in ("BEFORE", "CODING", "PENDING_SYSTEM_TEST", "SYSTEM_TEST"):
            self.assertFalse(isContestOver(phase, START, DURATION, longAfter), phase)

    def test_a_finished_flag_set_before_the_clock_says_so_is_not_trusted(self):
        self.assertFalse(isContestOver("FINISHED", START, DURATION, START + timedelta(minutes=30)))


def problem(problemId, contestId, status="SCRAPED_WAITING_FOR_CONTEST"):
    return {"id": problemId, "contest_id": contestId, "stage_status": status}

def contest(contestId, phase="FINISHED", start=START, duration=DURATION):
    return {"id": contestId, "phase": phase, "start_time": start.isoformat(), "duration_seconds": duration}

NOW = END + COOLDOWN + timedelta(hours=1)


class PlanPromotionsTests(unittest.TestCase):
    def test_promotes_only_problems_whose_contest_is_over(self):
        problems = [problem("1_A", 1), problem("2_A", 2), problem("3_A", 3)]
        contests = [contest(1), contest(2, phase="CODING"), contest(3, start=NOW - timedelta(hours=1))]
        self.assertEqual(planPromotions(problems, contests, NOW), ["1_A"])

    def test_a_problem_whose_contest_row_is_missing_stays_put(self):
        self.assertEqual(planPromotions([problem("9_A", 9)], [contest(1)], NOW), [])

    def test_only_waiting_problems_are_considered(self):
        problems = [problem("1_A", 1, "DUPLICATE"), problem("1_B", 1, "HINTS_GENERATED"), problem("1_C", 1)]
        self.assertEqual(planPromotions(problems, [contest(1)], NOW), ["1_C"])

    def test_timestamps_with_a_z_suffix_are_understood(self):
        row = contest(1)
        row["start_time"] = "2024-01-01T12:00:00Z"
        self.assertEqual(planPromotions([problem("1_A", 1)], [row], NOW), ["1_A"])

    def test_order_follows_the_input(self):
        problems = [problem("1_B", 1), problem("1_A", 1)]
        self.assertEqual(planPromotions(problems, [contest(1)], NOW), ["1_B", "1_A"])


class RunTests(unittest.TestCase):
    def makeClient(self, problemCount=3):
        problems = [problem(f"1_{i:03d}", 1) for i in range(problemCount)]
        problems += [problem("2_A", 2), problem("1_Z", 1, "TUTORIAL_FOUND")]
        return FakeSupabase({"problems": problems, "contests": [contest(1), contest(2, phase="CODING")]})

    def test_promotes_eligible_problems_with_a_guarded_update(self):
        client = self.makeClient()
        result = run(client, now=NOW)

        updates = client.writes("problems", "update")
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0].payload["stage_status"], "WAITING_FOR_TUTORIAL")
        self.assertEqual(updates[0].payload["updated_at"], "now()")
        self.assertEqual(updates[0].inFilters, [("id", ["1_000", "1_001", "1_002"])])
        # another worker may have moved the row in the meantime: only waiting rows may be changed
        self.assertEqual(updates[0].eqFilters, [("stage_status", "SCRAPED_WAITING_FOR_CONTEST")])
        self.assertEqual(result, {"promoted": 3, "still_waiting": 1})

    def test_only_waiting_problems_are_read(self):
        client = self.makeClient()
        run(client, now=NOW)
        problemReads = client.selects("problems")
        self.assertTrue(all(call.eqFilters == [("stage_status", "SCRAPED_WAITING_FOR_CONTEST")] for call in problemReads))

    def test_dry_run_changes_nothing(self):
        client = self.makeClient()
        result = run(client, now=NOW, dryRun=True)
        self.assertEqual(client.writes("problems", "update"), [])
        self.assertEqual(result, {"promoted": 3, "still_waiting": 1})

    def test_nothing_eligible_means_no_write(self):
        client = FakeSupabase({"problems": [problem("2_A", 2)], "contests": [contest(2, phase="CODING")]})
        result = run(client, now=NOW)
        self.assertEqual(client.writes("problems", "update"), [])
        self.assertEqual(result, {"promoted": 0, "still_waiting": 1})

    def test_no_waiting_problems(self):
        client = FakeSupabase({"problems": [], "contests": []})
        self.assertEqual(run(client, now=NOW), {"promoted": 0, "still_waiting": 0})

    def test_updates_are_chunked(self):
        client = self.makeClient(problemCount=PROMOTE_CHUNK_SIZE + 5)
        run(client, now=NOW)
        updates = client.writes("problems", "update")
        self.assertEqual([len(call.inFilters[0][1]) for call in updates], [PROMOTE_CHUNK_SIZE, 5])


if __name__ == "__main__":
    unittest.main()
