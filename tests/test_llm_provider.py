import contextlib
import io
import unittest

from src.services.llm.errors import (
    LlmBlockedError,
    LlmConfigurationError,
    LlmRequestError,
    TransientLlmError,
)
from src.services.llm.llmProvider import FallbackLlm, createClientFromEnvironment


class Scripted:
    """A stand-in model client: answers, or raises, what it is told to."""
    def __init__(self, model, *outcomes):
        self.model = model
        self.outcomes = list(outcomes)
        self.calls = 0
        self.requests = 0

    def generate(self, system, user, schema):
        self.calls += 1
        if self.calls > 10:  # a chain that keeps asking the same failing model would otherwise loop forever
            raise AssertionError(f"{self.model} was called {self.calls} times")
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        self.requests += 1
        return outcome

    def usageSummary(self):
        return f"{self.requests} request(s)"


def quiet(callable_):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        result = callable_()
    return result, out.getvalue()


class FallbackTests(unittest.TestCase):
    def test_uses_the_first_model_while_it_works(self):
        first, second = Scripted("argon", "A"), Scripted("flash", "B")
        chain = FallbackLlm([first, second])
        self.assertEqual(chain.generate("s", "u", {}), "A")
        self.assertEqual((first.calls, second.calls, chain.model), (1, 0, "argon"))

    def test_a_request_error_such_as_closed_billing_moves_to_the_next_model_for_good(self):
        first, second = Scripted("argon", LlmRequestError("HTTP 403: billing closed")), Scripted("flash", "B")
        chain = FallbackLlm([first, second])
        result, printed = quiet(lambda: chain.generate("s", "u", {}))
        self.assertEqual(result, "B")
        self.assertEqual(chain.model, "flash")  # the model that wrote the answer is the one recorded with the hints
        self.assertIn("argon", printed)
        self.assertIn("flash", printed)
        self.assertIn("billing closed", printed)
        chain.generate("s", "u", {})
        self.assertEqual(first.calls, 1)  # never asked again

    def test_other_errors_do_not_trigger_the_switch(self):
        for error in (TransientLlmError("429"), LlmBlockedError("blocked")):
            first, second = Scripted("argon", error), Scripted("flash", "B")
            chain = FallbackLlm([first, second])
            with self.assertRaises(type(error)):
                chain.generate("s", "u", {})
            self.assertEqual(second.calls, 0)

    def test_when_every_model_fails_the_last_error_surfaces(self):
        chain = FallbackLlm([Scripted("a", LlmRequestError("first")), Scripted("b", LlmRequestError("second"))])
        with self.assertRaises(LlmRequestError) as caught:
            quiet(lambda: chain.generate("s", "u", {}))
        self.assertIn("second", str(caught.exception))

    def test_the_usage_line_covers_every_model_that_was_used(self):
        first, second = Scripted("argon", "A"), Scripted("flash", "B")
        chain = FallbackLlm([first, second])
        chain.generate("s", "u", {})
        summary = chain.usageSummary()
        self.assertIn("argon: 1 request(s)", summary)
        self.assertNotIn("flash", summary)

    def test_a_single_client_needs_no_chain(self):
        self.assertTrue(hasattr(FallbackLlm([Scripted("a", "A")]), "generate"))


class FactoryTests(unittest.TestCase):
    TOKENS = type("T", (), {"token": lambda self: "t", "project": lambda self: "p"})()

    def test_vertex_is_a_provider(self):
        client = createClientFromEnvironment({"LLM_PROVIDER": "vertex", "VERTEX_PROJECT": "p"}, tokenProvider=self.TOKENS)
        self.assertEqual(client.model, "gemini-4-argon")

    def test_a_comma_separated_list_is_a_fallback_chain_in_order(self):
        client = createClientFromEnvironment(
            {"LLM_PROVIDER": "vertex, gemini", "VERTEX_PROJECT": "p", "GEMINI_API_KEY": "k", "GEMINI_MODEL": "gemini-3.8-flash"},
            tokenProvider=self.TOKENS)
        self.assertIsInstance(client, FallbackLlm)
        self.assertEqual([c.model for c in client.clients], ["gemini-4-argon", "gemini-3.8-flash"])

    def test_a_misconfigured_fallback_is_caught_at_start_not_after_the_credit_runs_out(self):
        with self.assertRaises(LlmConfigurationError) as caught:
            createClientFromEnvironment({"LLM_PROVIDER": "vertex,gemini", "VERTEX_PROJECT": "p"}, tokenProvider=self.TOKENS)
        self.assertIn("GEMINI_API_KEY", str(caught.exception))

    def test_blank_entries_are_ignored_and_unknown_ones_refused(self):
        client = createClientFromEnvironment({"LLM_PROVIDER": "vertex,", "VERTEX_PROJECT": "p"}, tokenProvider=self.TOKENS)
        self.assertNotIsInstance(client, FallbackLlm)
        with self.assertRaises(LlmConfigurationError) as caught:
            createClientFromEnvironment({"LLM_PROVIDER": "vertex,openai", "VERTEX_PROJECT": "p"}, tokenProvider=self.TOKENS)
        self.assertIn("openai", str(caught.exception))

    def test_the_existing_single_providers_still_work(self):
        self.assertEqual(createClientFromEnvironment({"ANTHROPIC_API_KEY": "k"}).model, "claude-opus-5-5")
        self.assertEqual(createClientFromEnvironment({"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "k", "GEMINI_MODEL": "m"}).model, "m")


if __name__ == "__main__":
    unittest.main()
