import contextlib
import io
import json
import unittest
from datetime import datetime, timedelta, timezone

from src.services.llm.geminiClient import (
    LlmBlockedError,
    LlmConfigurationError,
    LlmRequestError,
    LlmTruncatedError,
    TransientLlmError,
)
from src.services.llm.hintPrompt import PROMPT_VERSION, RESPONSE_SCHEMA, SYSTEM_PROMPT
from src.workers.hint_generator.generateHints import (
    MAX_CONSECUTIVE_TRANSIENT_FAILURES,
    MAX_FORMAT_RETRIES,
    MAX_HINT_ATTEMPTS,
    run,
)
from tests.fakeSupabase import FakeSupabase

NOW = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
LONG_AGO = NOW - timedelta(days=200)


def goodAnswer(prefix="") -> str:
    return json.dumps({"hints": [
        {"level": level, "text": f"{prefix}Level {level}: a calm observation about the numbers in this problem."}
        for level in range(1, 6)
    ]})

def answerWithHints(count: int) -> str:
    return json.dumps({"hints": [
        {"level": level, "text": f"Level {level}: a calm observation about the numbers in this problem."}
        for level in range(1, count + 1)
    ]})

def badAnswer() -> str:
    answer = json.loads(goodAnswer())
    answer["hints"][0]["text"] = "Level 1: this is clearly a dynamic programming problem about the numbers."
    return json.dumps(answer)


class FakeLlm:
    model = "fake-model"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def generate(self, system, user, schema):
        self.calls.append({"system": system, "user": user, "schema": schema})
        answer = self.answers.pop(0) if self.answers else goodAnswer()
        if isinstance(answer, Exception):
            raise answer
        return answer


def contest(contestId, start=LONG_AGO, phase="FINISHED", duration=7200):
    return {"id": contestId, "phase": phase, "start_time": start.isoformat(), "duration_seconds": duration}

def problem(problemId, contestId=1, status="TUTORIAL_FOUND", attempts=0):
    return {"id": problemId, "name": f"Problem {problemId}", "rating": 1200, "tags": ["math"],
            "contest_id": contestId, "stage_status": status, "hint_attempts": attempts}

def specs(problemId, **overrides):
    row = {"problem_id": problemId, "time_limit_ms": 2000, "memory_limit_mb": 256,
           "statement_text": f"Statement of {problemId}.", "input_specification": "Input\n\nIn.",
           "output_specification": "Output\n\nOut.", "interaction_specification": None, "notes": None}
    row.update(overrides)
    return row

def world(problems=None, contests=None, withTutorials=True, withSpecs=True):
    problems = problems if problems is not None else [problem("1_A")]
    return FakeSupabase({
        "problems": problems,
        "contests": contests if contests is not None else [contest(1)],
        "problem_specifications": [specs(p["id"]) for p in problems] if withSpecs else [],
        "sample_tests": [{"problem_id": p["id"], "test_order": n, "input_text": f"in{n}", "output_text": f"out{n}"}
                         for p in problems for n in (2, 1)],
        "tutorials": [{"problem_id": p["id"], "raw_content": f"Editorial of {p['id']}."} for p in problems] if withTutorials else [],
    })

def go(client, llm, **kwargs):
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("delaySeconds", 0)
    kwargs.setdefault("sleep", lambda seconds: None)
    return run(client, llm, **kwargs)

def hintRows(client):
    return [row for call in client.writes("hints", "upsert") for row in call.payload]

def updatesOf(client):
    return client.writes("problems", "update")


class SuccessTests(unittest.TestCase):
    def test_five_hints_are_written_in_one_upsert_then_the_status_moves(self):
        client, llm = world(), FakeLlm()
        result = go(client, llm)

        upserts = client.writes("hints", "upsert")
        self.assertEqual(len(upserts), 1)
        self.assertEqual(upserts[0].onConflict, "problem_id,hint_level")
        rows = upserts[0].payload
        self.assertEqual([row["hint_level"] for row in rows], [1, 2, 3, 4, 5])
        self.assertEqual(rows[0], {
            "problem_id": "1_A", "hint_level": 1, "content": "Level 1: a calm observation about the numbers in this problem.",
            "llm_model_used": "fake-model", "prompt_version": PROMPT_VERSION, "grounded_in_tutorial": True, "created_at": "now()",
        })
        update = updatesOf(client)[0]
        self.assertEqual(update.payload, {"stage_status": "HINTS_GENERATED", "last_error": None, "updated_at": "now()"})
        self.assertEqual(update.eqFilters, [("id", "1_A"), ("stage_status", "TUTORIAL_FOUND")])
        self.assertEqual(result["generated"], 1)

    def test_hints_are_stored_before_stale_levels_go_and_the_status_changes_last(self):
        client = world()
        go(client, FakeLlm())
        order = [(call.tableName, call.operation) for call in client.calls if call.operation in ("upsert", "update", "delete")]
        self.assertEqual(order, [("hints", "upsert"), ("hints", "delete"), ("problems", "update")])

    def test_a_problem_may_get_between_two_and_five_hints(self):
        for count in (2, 3, 4, 5):
            client = world()
            result = go(client, FakeLlm(answerWithHints(count)))
            self.assertEqual([row["hint_level"] for row in hintRows(client)], list(range(1, count + 1)), count)
            self.assertEqual(result["generated"], 1)

    def test_levels_above_the_new_count_are_removed_so_a_regeneration_cannot_leave_old_hints_behind(self):
        client = world()
        go(client, FakeLlm(answerWithHints(3)))
        delete = client.writes("hints", "delete")[0]
        self.assertEqual(delete.eqFilters, [("problem_id", "1_A")])
        self.assertEqual(delete.gtFilters, [("hint_level", 3)])

    def test_nothing_is_deleted_in_a_dry_run(self):
        client = world()
        go(client, FakeLlm(), dryRun=True)
        self.assertEqual(client.writes("hints", "delete"), [])

    def test_the_model_sees_the_problem_samples_and_editorial(self):
        client, llm = world(), FakeLlm()
        go(client, llm)
        call = llm.calls[0]
        self.assertEqual(call["system"], SYSTEM_PROMPT)
        self.assertEqual(call["schema"], RESPONSE_SCHEMA)
        for fragment in ("Statement of 1_A.", "Editorial of 1_A.", "in1", "out2"):
            self.assertIn(fragment, call["user"])
        self.assertLess(call["user"].index("in1"), call["user"].index("in2"))

    def test_an_interactive_problem_is_sent_with_its_interaction_text(self):
        client = world()
        client.tables["problem_specifications"] = [specs("1_A", output_specification=None, interaction_specification="Interaction\n\nPrint ? x.")]
        llm = FakeLlm()
        go(client, llm)
        self.assertIn("Print ? x.", llm.calls[0]["user"])


class SelectionTests(unittest.TestCase):
    def test_only_tutorial_found_problems_by_default(self):
        client = world([problem("1_A", status="WAITING_FOR_TUTORIAL"), problem("1_B", status="DUPLICATE"),
                        problem("1_C", status="DISCOVERED"), problem("1_D", status="HINTS_GENERATED"), problem("1_E", status="FAILED")])
        llm = FakeLlm()
        go(client, llm)
        self.assertEqual(llm.calls, [])

    def test_waiting_problems_are_used_only_when_asked_and_old_enough(self):
        old = contest(1, start=NOW - timedelta(days=8))
        recent = contest(2, start=NOW - timedelta(days=3))
        client = world([problem("1_A", 1, "WAITING_FOR_TUTORIAL"), problem("2_A", 2, "WAITING_FOR_TUTORIAL")], [old, recent], withTutorials=False)
        llm = FakeLlm()
        result = go(client, llm, includeWithoutTutorial=True, noTutorialAfterDays=7)

        self.assertEqual(len(llm.calls), 1)
        self.assertIn("1_A", llm.calls[0]["user"])
        self.assertIn("No official editorial", llm.calls[0]["user"])
        self.assertFalse(hintRows(client)[0]["grounded_in_tutorial"])
        self.assertEqual(updatesOf(client)[0].eqFilters, [("id", "1_A"), ("stage_status", "WAITING_FOR_TUTORIAL")])
        self.assertEqual(result["generated"], 1)

    def test_the_waiting_threshold_is_configurable(self):
        recent = contest(2, start=NOW - timedelta(days=3))
        client = world([problem("2_A", 2, "WAITING_FOR_TUTORIAL")], [recent], withTutorials=False)
        llm = FakeLlm()
        go(client, llm, includeWithoutTutorial=True, noTutorialAfterDays=2)
        self.assertEqual(len(llm.calls), 1)

    def test_a_problem_whose_contest_is_not_over_is_never_generated_even_with_the_right_status(self):
        for badContest in (contest(1, start=NOW - timedelta(hours=1), phase="CODING"),
                           contest(1, start=NOW - timedelta(hours=3), phase="FINISHED", duration=7200)):
            client, llm = world([problem("1_A")], [badContest]), FakeLlm()
            result = go(client, llm)
            self.assertEqual(llm.calls, [])
            self.assertEqual(hintRows(client), [])
            self.assertEqual(result["generated"], 0)

    def test_order_is_tutorial_first_then_fewest_attempts_then_id(self):
        old = contest(1, start=NOW - timedelta(days=30))
        client = world([problem("1_C", status="WAITING_FOR_TUTORIAL"), problem("1_B", attempts=2),
                        problem("1_A", attempts=2), problem("1_D", attempts=0)], [old])
        llm = FakeLlm()
        go(client, llm, includeWithoutTutorial=True)
        order = [next(p for p in ("1_A", "1_B", "1_C", "1_D") if f"Problem {p}:" in call["user"]) for call in llm.calls]
        self.assertEqual(order, ["1_D", "1_A", "1_B", "1_C"])

    def test_limit_bounds_the_number_of_model_calls(self):
        client = world([problem(f"1_{n}") for n in "ABCDE"])
        llm = FakeLlm()
        go(client, llm, limit=2)
        self.assertEqual(len(llm.calls), 2)

    def test_a_single_problem_can_be_asked_for(self):
        client = world([problem("1_A"), problem("1_B")])
        llm = FakeLlm()
        go(client, llm, onlyProblemId="1_B")
        self.assertEqual(len(llm.calls), 1)
        self.assertIn("Problem 1_B:", llm.calls[0]["user"])

    def test_waits_between_model_calls_but_not_before_the_first(self):
        client = world([problem(f"1_{n}") for n in "ABC"])
        sleeps = []
        go(client, FakeLlm(), delaySeconds=3.0, sleep=sleeps.append)
        self.assertEqual(sleeps, [3.0, 3.0])


class RejectedAnswerTests(unittest.TestCase):
    def test_a_rejected_answer_is_retried_with_the_reason_quoted_back(self):
        client, llm = world(), FakeLlm(badAnswer(), goodAnswer("second try "))
        result = go(client, llm)

        self.assertEqual(len(llm.calls), 2)
        self.assertNotIn("rejected", llm.calls[0]["user"])
        self.assertIn("rejected", llm.calls[1]["user"])
        self.assertIn("dynamic programming", llm.calls[1]["user"])
        self.assertTrue(hintRows(client)[0]["content"].startswith("second try"))
        self.assertEqual(result["generated"], 1)

    def test_giving_up_records_the_attempt_and_leaves_the_status(self):
        client, llm = world(), FakeLlm(*[badAnswer()] * (1 + MAX_FORMAT_RETRIES))
        result = go(client, llm)

        self.assertEqual(len(llm.calls), 1 + MAX_FORMAT_RETRIES)
        self.assertEqual(hintRows(client), [])
        update = updatesOf(client)[0]
        self.assertEqual(update.payload["hint_attempts"], 1)
        self.assertIn("dynamic programming", update.payload["last_error"])
        self.assertNotIn("stage_status", update.payload)
        self.assertEqual(result, {"generated": 0, "failed": 0, "retry_later": 1, "transient_failures": 0})

    def test_the_last_allowed_attempt_marks_the_problem_failed(self):
        client = world([problem("1_A", attempts=MAX_HINT_ATTEMPTS - 1)])
        result = go(client, FakeLlm(*[badAnswer()] * (1 + MAX_FORMAT_RETRIES)))
        update = updatesOf(client)[0]
        self.assertEqual(update.payload["stage_status"], "FAILED")
        self.assertEqual(update.payload["hint_attempts"], MAX_HINT_ATTEMPTS)
        self.assertEqual(result["failed"], 1)

    def test_a_blocked_problem_counts_as_a_failed_attempt(self):
        client = world()
        result = go(client, FakeLlm(LlmBlockedError("The prompt was blocked (SAFETY).")))
        self.assertIn("blocked", updatesOf(client)[0].payload["last_error"])
        self.assertEqual(result["retry_later"], 1)

    def test_an_answer_cut_off_at_the_output_limit_counts_as_a_failed_attempt(self):
        client = world()
        result = go(client, FakeLlm(LlmTruncatedError("The answer was cut off at 16000 output tokens.")))
        self.assertIn("cut off", updatesOf(client)[0].payload["last_error"])
        self.assertEqual(updatesOf(client)[0].payload["hint_attempts"], 1)
        self.assertEqual(result["retry_later"], 1)

    def test_missing_specifications_are_recorded_not_sent_to_the_model(self):
        client, llm = world(withSpecs=False), FakeLlm()
        go(client, llm)
        self.assertEqual(llm.calls, [])
        self.assertIn("specification", updatesOf(client)[0].payload["last_error"])

    def test_a_tutorial_found_problem_without_a_tutorial_row_is_not_silently_ungrounded(self):
        client, llm = world(withTutorials=False), FakeLlm()
        go(client, llm)
        self.assertEqual(llm.calls, [])
        self.assertIn("tutorial", updatesOf(client)[0].payload["last_error"])


class DatabaseTroubleTests(unittest.TestCase):
    """A dropped database connection must neither crash the run nor waste a paid answer when avoidable."""

    def world(self, networkFailures, problems=None):
        client = world(problems)
        client.networkFailures = dict(networkFailures)
        return client

    def test_a_blip_while_loading_the_problem_is_retried(self):
        client = self.world({("problem_specifications", "select"): 1})
        llm = FakeLlm()
        result = go(client, llm)
        self.assertEqual(result["generated"], 1)
        self.assertEqual(len(llm.calls), 1)

    def test_a_blip_while_saving_is_retried_without_asking_the_model_again(self):
        client = self.world({("hints", "upsert"): 2})
        llm = FakeLlm()
        result = go(client, llm)
        self.assertEqual(result["generated"], 1)
        self.assertEqual(len(llm.calls), 1)  # the paid answer was not thrown away
        self.assertEqual(len(client.writes("hints", "upsert")), 3)
        self.assertEqual(updatesOf(client)[0].payload["stage_status"], "HINTS_GENERATED")

    def test_a_database_that_stays_down_changes_nothing_and_is_not_a_failed_attempt(self):
        client = self.world({("problem_specifications", "select"): 999})
        llm = FakeLlm()
        result = go(client, llm)
        self.assertEqual(llm.calls, [])
        self.assertEqual(updatesOf(client), [])
        self.assertEqual(result["transient_failures"], 1)
        self.assertEqual(result["retry_later"], 0)

    def test_losing_the_database_after_the_answer_leaves_the_problem_unchanged(self):
        client = self.world({("hints", "upsert"): 999})
        result = go(client, FakeLlm())
        self.assertEqual(updatesOf(client), [])  # still TUTORIAL_FOUND, no attempt used
        self.assertEqual(result["generated"], 0)
        self.assertEqual(result["transient_failures"], 1)

    def test_the_run_stops_when_the_database_keeps_failing(self):
        count = MAX_CONSECUTIVE_TRANSIENT_FAILURES + 3
        client = self.world({("problem_specifications", "select"): 9999}, [problem(f"1_{i:02d}") for i in range(count)])
        result = go(client, FakeLlm())
        self.assertEqual(result["transient_failures"], MAX_CONSECUTIVE_TRANSIENT_FAILURES)

    def test_failing_to_record_a_failure_does_not_crash_the_run(self):
        client = self.world({("problems", "update"): 999})
        result = go(client, FakeLlm(*[badAnswer()] * (1 + MAX_FORMAT_RETRIES)))
        self.assertEqual(result["generated"], 0)


class ProviderTroubleTests(unittest.TestCase):
    def test_a_transient_error_changes_nothing_and_the_run_goes_on(self):
        client = world([problem("1_A"), problem("1_B")])
        result = go(client, FakeLlm(TransientLlmError("HTTP 429")))
        self.assertEqual([row["problem_id"] for row in hintRows(client)][:1], ["1_B"])
        self.assertEqual(result["generated"], 1)
        self.assertEqual(result["transient_failures"], 1)
        self.assertEqual([u.eqFilters[0] for u in updatesOf(client)], [("id", "1_B")])

    def test_the_run_stops_after_too_many_transient_errors_in_a_row(self):
        count = MAX_CONSECUTIVE_TRANSIENT_FAILURES + 3
        client = world([problem(f"1_{i:02d}") for i in range(count)])
        llm = FakeLlm(*[TransientLlmError("HTTP 503")] * count)
        result = go(client, llm)
        self.assertEqual(len(llm.calls), MAX_CONSECUTIVE_TRANSIENT_FAILURES)
        self.assertEqual(result["transient_failures"], MAX_CONSECUTIVE_TRANSIENT_FAILURES)

    def test_a_success_resets_the_streak(self):
        n = MAX_CONSECUTIVE_TRANSIENT_FAILURES
        answers = [TransientLlmError("x")] * (n - 1) + [goodAnswer()] + [TransientLlmError("x")] * (n - 1)
        client = world([problem(f"1_{i:02d}") for i in range(len(answers))])
        llm = FakeLlm(*answers)
        go(client, llm, limit=100)
        self.assertEqual(len(llm.calls), len(answers))

    def test_a_bad_key_or_model_stops_everything_and_writes_nothing(self):
        for error in (LlmRequestError("HTTP 404: model not found"), LlmConfigurationError("GEMINI_MODEL is not set")):
            client = world([problem("1_A"), problem("1_B")])
            llm = FakeLlm(error)
            with self.assertRaises(LlmRequestError):
                go(client, llm)
            self.assertEqual(len(llm.calls), 1)
            self.assertEqual(client.writes("hints", "upsert"), [])
            self.assertEqual(updatesOf(client), [])


class UsageReportTests(unittest.TestCase):
    class MeteredLlm(FakeLlm):
        def usageSummary(self):
            return "3 request(s), 9,000 input + 4,000 output tokens, about $0.12 at test list prices"

    def output(self, client, llm, **kwargs):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            try:
                go(client, llm, **kwargs)
            except LlmRequestError:
                pass
        return buffer.getvalue()

    def test_the_run_ends_by_reporting_what_it_cost(self):
        text = self.output(world(), self.MeteredLlm())
        self.assertIn("Usage: 3 request(s), 9,000 input + 4,000 output tokens", text)

    def test_the_cost_is_reported_even_when_the_run_stops_on_a_bad_key(self):
        text = self.output(world(), self.MeteredLlm(LlmRequestError("HTTP 400: credit balance is too low")))
        self.assertIn("Usage:", text)

    def test_a_client_without_metering_is_fine(self):
        self.assertNotIn("Usage:", self.output(world(), FakeLlm()))


class DryRunTests(unittest.TestCase):
    def test_dry_run_calls_the_model_but_writes_nothing(self):
        client, llm = world(), FakeLlm(badAnswer(), badAnswer(), badAnswer())
        go(client, llm, dryRun=True)
        self.assertEqual(len(llm.calls), 3)
        self.assertEqual(client.writes("hints", "upsert"), [])
        self.assertEqual(updatesOf(client), [])

    def test_dry_run_reports_what_would_be_generated(self):
        client = world()
        result = go(client, FakeLlm(), dryRun=True)
        self.assertEqual(result["generated"], 1)
        self.assertEqual(client.writes("hints", "upsert"), [])
        self.assertEqual(updatesOf(client), [])


if __name__ == "__main__":
    unittest.main()
