import unittest

from src.services.llm.errors import LlmRequestError
from src.workers.backfill.runBackfill import (
    QUOTA_ERRORS_IN_A_ROW,
    Stages,
    runBackfill,
    statusCounts,
)
from tests.fakeSupabase import FakeSupabase


def problems(**counts):
    rows = []
    for status, count in counts.items():
        rows += [{"id": f"{status}-{i}", "stage_status": status} for i in range(count)]
    return rows

def client(**counts):
    return FakeSupabase({"problems": problems(**counts)})


class Script:
    """Stage stand-ins that return scripted results and record the order they ran in."""
    def __init__(self, protector=None, finder=None, generator=None, afterPass=None):
        self.log = []
        self.protectorResults = list(protector or [{"promoted": 0, "still_waiting": 0}])
        self.finderResults = list(finder or [{"found": 0, "no_tutorial_yet": 0, "transient_failures": 0}])
        self.generatorResults = list(generator or [{"generated": 0, "failed": 0, "transient_failures": 0}])
        self.afterPass = afterPass
        self.includeFlags = []

    def next(self, results):
        return results.pop(0) if len(results) > 1 else results[0]

    def stages(self):
        def protector():
            self.log.append("protector")
            return self.next(self.protectorResults)

        def finder():
            self.log.append("finder")
            return self.next(self.finderResults)

        def generator(includeWithoutTutorial):
            self.log.append("generator")
            self.includeFlags.append(includeWithoutTutorial)
            result = self.next(self.generatorResults)
            if self.afterPass:
                self.afterPass()
            return result

        return Stages(protector=protector, finder=finder, generator=generator)


def run(db, script, **kwargs):
    sleeps = []
    kwargs.setdefault("maxPasses", 20)
    runBackfill(db, script.stages(), sleep=sleeps.append, log=lambda message: None, idleSeconds=600, quotaPauseSeconds=1800, **kwargs)
    return sleeps


class StatusTests(unittest.TestCase):
    def test_counts_problems_by_status(self):
        self.assertEqual(statusCounts(client(DISCOVERED=3, HINTS_GENERATED=2)), {"DISCOVERED": 3, "HINTS_GENERATED": 2})


class PassTests(unittest.TestCase):
    def test_every_pass_runs_the_protector_then_the_finder_then_the_generator(self):
        script = Script(generator=[{"generated": 5, "failed": 0, "transient_failures": 0}, {"generated": 0, "failed": 0, "transient_failures": 0}])
        run(client(DISCOVERED=2), script, maxPasses=2)
        self.assertEqual(script.log, ["protector", "finder", "generator"] * 2)

    def test_it_keeps_going_without_pausing_while_there_is_progress(self):
        script = Script(generator=[{"generated": 5, "failed": 0, "transient_failures": 0}] * 3)
        sleeps = run(client(DISCOVERED=2), script, maxPasses=3)
        self.assertEqual(sleeps, [])

    def test_with_no_progress_it_waits_and_looks_again(self):
        sleeps = run(client(DISCOVERED=2), Script(), maxPasses=3)  # scraping is still going: nothing to do yet
        self.assertEqual(sleeps, [600, 600])

    def test_hitting_the_quota_waits_much_longer(self):
        script = Script(generator=[{"generated": 3, "failed": 0, "transient_failures": QUOTA_ERRORS_IN_A_ROW}])
        sleeps = run(client(DISCOVERED=2), script, maxPasses=2)
        self.assertEqual(sleeps, [1800])


class UngroundedHintsTests(unittest.TestCase):
    def test_hints_without_a_tutorial_stay_off_while_scraping_is_still_going(self):
        script = Script()
        run(client(DISCOVERED=5), script, maxPasses=2)
        self.assertEqual(script.includeFlags, [False, False])

    def test_they_stay_off_while_the_finder_is_still_finding_or_checking_contests(self):
        for finderResult in ({"found": 4, "no_tutorial_yet": 0, "transient_failures": 0},
                             {"found": 0, "no_tutorial_yet": 2, "transient_failures": 0},
                             {"found": 0, "no_tutorial_yet": 0, "transient_failures": 1}):
            script = Script(finder=[finderResult])
            run(client(WAITING_FOR_TUTORIAL=5), script, maxPasses=1)
            self.assertEqual(script.includeFlags, [False], finderResult)

    def test_they_switch_on_once_scraping_is_over_and_the_finder_has_nothing_left_to_check(self):
        script = Script()
        run(client(WAITING_FOR_TUTORIAL=5), script, maxPasses=1)
        self.assertEqual(script.includeFlags, [True])


class FinishTests(unittest.TestCase):
    def test_it_stops_by_itself_when_everything_is_done(self):
        script = Script()
        sleeps = run(client(HINTS_GENERATED=10, DUPLICATE=2, FAILED=1), script, maxPasses=50)
        self.assertEqual(script.log, ["protector", "finder", "generator"])  # one last pass, then done
        self.assertEqual(sleeps, [])

    def test_waiting_problems_whose_contest_is_too_recent_do_not_keep_it_running_forever(self):
        script = Script()
        run(client(WAITING_FOR_TUTORIAL=3, HINTS_GENERATED=10), script, maxPasses=50)
        self.assertEqual(len(script.log), 3)

    def test_it_does_not_stop_while_scraping_is_unfinished(self):
        script = Script()
        run(client(DISCOVERED=1), script, maxPasses=4)
        self.assertEqual(len(script.log), 12)

    def test_new_problems_appearing_during_a_pass_keep_it_running(self):
        db = client(HINTS_GENERATED=3)  # looks finished when the pass starts...
        script = Script(afterPass=lambda: db.tables["problems"].append({"id": "new", "stage_status": "DISCOVERED"}))
        run(db, script, maxPasses=3)  # ...but the sync adds a problem meanwhile
        self.assertEqual(len(script.log), 9)

    def test_it_does_not_stop_while_tutorials_are_waiting_for_their_hints(self):
        script = Script()
        run(client(TUTORIAL_FOUND=1), script, maxPasses=3)
        self.assertEqual(len(script.log), 9)

    def test_it_stops_after_the_requested_number_of_passes(self):
        script = Script(generator=[{"generated": 1, "failed": 0, "transient_failures": 0}])
        run(client(DISCOVERED=1), script, maxPasses=3)
        self.assertEqual(script.log.count("generator"), 3)


class FailureTests(unittest.TestCase):
    def test_a_bad_key_stops_everything_instead_of_looping(self):
        script = Script()
        script.stages_ = script.stages()
        def broken(includeWithoutTutorial):
            raise LlmRequestError("HTTP 400: key not valid")
        stages = Stages(protector=lambda: {"promoted": 0}, finder=lambda: {"found": 0, "no_tutorial_yet": 0, "transient_failures": 0}, generator=broken)
        with self.assertRaises(LlmRequestError):
            runBackfill(client(TUTORIAL_FOUND=1), stages, sleep=lambda s: None, log=lambda m: None, maxPasses=5)

    def test_an_unexpected_crash_in_a_pass_is_logged_and_survived(self):
        calls = []
        def flaky(includeWithoutTutorial):
            calls.append(1)
            if len(calls) == 1:
                raise ValueError("a bug")
            return {"generated": 1, "failed": 0, "transient_failures": 0}
        messages, sleeps = [], []
        stages = Stages(protector=lambda: {"promoted": 0}, finder=lambda: {"found": 0, "no_tutorial_yet": 0, "transient_failures": 0}, generator=flaky)
        runBackfill(client(DISCOVERED=1), stages, sleep=sleeps.append, log=messages.append, maxPasses=2, idleSeconds=600)
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [600])
        self.assertTrue(any("a bug" in message for message in messages))

    def test_repeated_crashes_end_the_run(self):
        def always(includeWithoutTutorial):
            raise ValueError("still broken")
        stages = Stages(protector=lambda: {"promoted": 0}, finder=lambda: {"found": 0, "no_tutorial_yet": 0, "transient_failures": 0}, generator=always)
        with self.assertRaises(ValueError):
            runBackfill(client(DISCOVERED=1), stages, sleep=lambda s: None, log=lambda m: None, maxPasses=50)


if __name__ == "__main__":
    unittest.main()
