import contextlib
import io
import unittest

from src.services.llm.errors import DailyQuotaExhaustedError, LlmRequestError, TransientLlmError
from src.services.llm.modelPool import GeminiModelPool


class Scripted:
    def __init__(self, model, *outcomes):
        self.model = model
        self.outcomes = list(outcomes)
        self.calls = 0
        self.requests = 0

    def generate(self, system, user, schema):
        self.calls += 1
        if self.calls > 50:
            raise AssertionError(f"{self.model} was called too often")
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        self.requests += 1
        return outcome

    def usageSummary(self):
        return f"{self.requests} request(s)"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def quiet(call):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        return call(), out.getvalue()


class PoolTests(unittest.TestCase):
    def test_the_first_model_answers_while_it_can(self):
        best, other = Scripted("best", "A"), Scripted("other", "B")
        pool = GeminiModelPool([best, other])
        self.assertEqual(pool.generate("s", "u", {}), "A")
        self.assertEqual((best.calls, other.calls, pool.model), (1, 0, "best"))

    def test_a_used_up_daily_quota_moves_to_the_next_model_and_the_first_is_left_alone_until_it_resets(self):
        clock = Clock()
        best = Scripted("best", DailyQuotaExhaustedError("used up", retryAfterSeconds=3600))
        other = Scripted("other", "B")
        pool = GeminiModelPool([best, other], now=clock)
        result, printed = quiet(lambda: pool.generate("s", "u", {}))
        self.assertEqual((result, pool.model), ("B", "other"))  # the model recorded with the hints is the one that answered
        self.assertIn("best", printed)
        pool.generate("s", "u", {})
        self.assertEqual(best.calls, 1)  # not asked again while blocked

    def test_the_better_model_is_used_again_after_its_quota_resets(self):
        clock = Clock()
        best = Scripted("best", DailyQuotaExhaustedError("used up", retryAfterSeconds=3600), "A-again")
        other = Scripted("other", "B")
        pool = GeminiModelPool([best, other], now=clock)
        quiet(lambda: pool.generate("s", "u", {}))
        clock.t += 3601
        self.assertEqual(pool.generate("s", "u", {}), "A-again")
        self.assertEqual(pool.model, "best")

    def test_an_overloaded_model_is_skipped_for_this_call_only(self):
        best = Scripted("best", TransientLlmError("HTTP 503"), "A")
        other = Scripted("other", "B")
        pool = GeminiModelPool([best, other])
        self.assertEqual(pool.generate("s", "u", {}), "B")
        self.assertEqual(pool.generate("s", "u", {}), "A")  # tried again on the next call, not blocked

    def test_when_every_model_is_out_of_quota_the_earliest_reset_is_reported(self):
        clock = Clock()
        pool = GeminiModelPool([
            Scripted("a", DailyQuotaExhaustedError("x", retryAfterSeconds=7200)),
            Scripted("b", DailyQuotaExhaustedError("y", retryAfterSeconds=1800)),
        ], now=clock)
        with self.assertRaises(DailyQuotaExhaustedError) as caught:
            quiet(lambda: pool.generate("s", "u", {}))
        self.assertEqual(caught.exception.retryAfterSeconds, 1800)
        # and now both are blocked: no more calls are made until a reset
        calls = [c.calls for c in pool.clients]
        with self.assertRaises(DailyQuotaExhaustedError):
            pool.generate("s", "u", {})
        self.assertEqual([c.calls for c in pool.clients], calls)

    def test_when_every_model_is_merely_overloaded_the_transient_error_surfaces(self):
        pool = GeminiModelPool([Scripted("a", TransientLlmError("503")), Scripted("b", TransientLlmError("429"))])
        with self.assertRaises(TransientLlmError) as caught:
            pool.generate("s", "u", {})
        self.assertNotIsInstance(caught.exception, DailyQuotaExhaustedError)

    def test_a_request_error_such_as_a_bad_key_is_not_hidden(self):
        pool = GeminiModelPool([Scripted("a", LlmRequestError("HTTP 400")), Scripted("b", "B")])
        with self.assertRaises(LlmRequestError):
            pool.generate("s", "u", {})

    def test_the_usage_line_names_each_model_that_was_used(self):
        pool = GeminiModelPool([Scripted("a", DailyQuotaExhaustedError("x", retryAfterSeconds=60)), Scripted("b", "B")])
        quiet(lambda: pool.generate("s", "u", {}))
        summary = pool.usageSummary()
        self.assertIn("b: 1 request(s)", summary)
        self.assertNotIn("a:", summary)

    def test_a_blocked_time_is_never_longer_than_a_day(self):
        clock = Clock()
        best = Scripted("best", DailyQuotaExhaustedError("x", retryAfterSeconds=10**7), "A")
        pool = GeminiModelPool([best, Scripted("other", "B")], now=clock)
        quiet(lambda: pool.generate("s", "u", {}))
        clock.t += 86401
        self.assertEqual(pool.generate("s", "u", {}), "A")


if __name__ == "__main__":
    unittest.main()
