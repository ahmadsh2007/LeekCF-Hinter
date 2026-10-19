import unittest

import requests

from src.services.llm.anthropicClient import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    MAX_OUTPUT_TOKENS,
    AnthropicClient,
    clientFromEnvironment,
)
from src.services.llm.geminiClient import (
    LlmBlockedError,
    LlmConfigurationError,
    LlmRequestError,
    LlmTruncatedError,
    TransientLlmError,
)
from src.services.llm.llmProvider import createClientFromEnvironment

SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


class FakeResponse:
    def __init__(self, status=200, body=None, badJson=False):
        self.status_code = status
        self.body = body
        self.badJson = badJson

    def json(self):
        if self.badJson:
            raise ValueError("not json")
        return self.body


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def message(*blocks, stopReason="end_turn", inputTokens=100, outputTokens=50):
    return {"content": list(blocks), "stop_reason": stopReason, "usage": {"input_tokens": inputTokens, "output_tokens": outputTokens}}

def text(value):
    return {"type": "text", "text": value}

def clientAnswering(*responses, **kwargs):
    session = FakeSession(*responses)
    return AnthropicClient("secret-key", session=session, **kwargs), session


class RequestShapeTests(unittest.TestCase):
    def test_defaults_are_opus_5_5_at_high_effort(self):
        self.assertEqual(DEFAULT_MODEL, "claude-opus-5-5")
        self.assertEqual(DEFAULT_EFFORT, "high")

    def test_posts_to_the_messages_api_with_the_key_in_a_header(self):
        client, session = clientAnswering(FakeResponse(200, message(text("{}"))))
        client.generate("SYSTEM", "USER", SCHEMA)

        call = session.calls[0]
        self.assertEqual(call["url"], "https://api.anthropic.com/v1/messages")
        self.assertEqual(call["headers"]["x-api-key"], "secret-key")
        self.assertEqual(call["headers"]["anthropic-version"], "2023-06-01")
        self.assertNotIn("secret-key", call["url"])

    def test_body_asks_for_the_model_effort_and_schema_constrained_json(self):
        client, session = clientAnswering(FakeResponse(200, message(text("{}"))))
        client.generate("SYSTEM", "USER", SCHEMA)

        body = session.calls[0]["json"]
        self.assertEqual(body["model"], "claude-opus-5-5")
        self.assertEqual(body["system"], "SYSTEM")
        self.assertEqual(body["messages"], [{"role": "user", "content": "USER"}])
        self.assertEqual(body["max_tokens"], MAX_OUTPUT_TOKENS)
        self.assertEqual(body["output_config"]["effort"], "high")
        self.assertEqual(body["output_config"]["format"], {"type": "json_schema", "schema": SCHEMA})
        # Sampling parameters are left to the model: adaptive thinking is always on for Opus 5.5.
        self.assertNotIn("temperature", body)
        self.assertNotIn("thinking", body)

    def test_model_and_effort_can_be_chosen(self):
        client, session = clientAnswering(FakeResponse(200, message(text("{}"))), model="claude-sonnet-5-5", effort="medium")
        client.generate("s", "u", SCHEMA)
        self.assertEqual(session.calls[0]["json"]["model"], "claude-sonnet-5-5")
        self.assertEqual(session.calls[0]["json"]["output_config"]["effort"], "medium")
        self.assertEqual(client.model, "claude-sonnet-5-5")

    def test_an_unknown_effort_level_is_refused_before_any_request(self):
        with self.assertRaises(LlmConfigurationError):
            AnthropicClient("k", effort="turbo", session=FakeSession())


class ResponseTests(unittest.TestCase):
    def test_only_text_blocks_are_the_answer_thinking_is_ignored(self):
        body = message({"type": "thinking", "thinking": "let me think...", "signature": "x"}, text('{"hints":'), text("[]}"))
        client, _ = clientAnswering(FakeResponse(200, body))
        self.assertEqual(client.generate("s", "u", SCHEMA), '{"hints":[]}')

    def test_token_usage_accumulates_across_calls(self):
        client, _ = clientAnswering(
            FakeResponse(200, message(text("{}"), inputTokens=1000, outputTokens=400)),
            FakeResponse(200, message(text("{}"), inputTokens=2000, outputTokens=600)),
        )
        client.generate("s", "u", SCHEMA)
        client.generate("s", "u", SCHEMA)
        self.assertEqual((client.requests, client.inputTokens, client.outputTokens), (2, 3000, 1000))

    def test_usage_summary_prices_tokens_at_list_prices(self):
        client, _ = clientAnswering(FakeResponse(200, message(text("{}"), inputTokens=1_000_000, outputTokens=1_000_000)))
        client.generate("s", "u", SCHEMA)
        summary = client.usageSummary()
        self.assertIn("1,000,000 input", summary)
        self.assertIn("1,000,000 output", summary)
        self.assertIn("$24.00", summary)  # $4 input + $20 output per million tokens

    def test_usage_summary_knows_the_prices_of_the_other_models_worth_comparing(self):
        for model, expected in (("claude-fable-5-1", "$60.00"), ("claude-sonnet-5-5", "$12.00")):  # per 1M in + 1M out
            client, _ = clientAnswering(FakeResponse(200, message(text("{}"), inputTokens=1_000_000, outputTokens=1_000_000)), model=model)
            client.generate("s", "u", SCHEMA)
            self.assertIn(expected, client.usageSummary(), model)

    def test_usage_summary_for_an_unpriced_model_has_no_dollar_figure(self):
        client, _ = clientAnswering(FakeResponse(200, message(text("{}"))), model="some-future-model")
        client.generate("s", "u", SCHEMA)
        self.assertNotIn("$", client.usageSummary())

    def test_refused_requests_are_still_counted_as_billed(self):
        client, _ = clientAnswering(FakeResponse(200, message(text("no"), stopReason="refusal", inputTokens=500, outputTokens=20)))
        with self.assertRaises(LlmBlockedError):
            client.generate("s", "u", SCHEMA)
        self.assertEqual(client.inputTokens, 500)


class ErrorTests(unittest.TestCase):
    def test_rate_limits_overload_server_errors_and_network_problems_are_transient(self):
        for response in (FakeResponse(429, {}), FakeResponse(529, {}), FakeResponse(500, {}), FakeResponse(408, {}),
                         requests.ConnectionError("down"), requests.Timeout("slow")):
            client, _ = clientAnswering(response)
            with self.assertRaises(TransientLlmError, msg=repr(response)):
                client.generate("s", "u", SCHEMA)

    def test_client_errors_stop_the_run_with_the_api_message_and_never_the_key(self):
        body = {"type": "error", "error": {"type": "invalid_request_error", "message": "Your credit balance is too low to access the API."}}
        for status in (400, 401, 403, 404, 413):
            client, _ = clientAnswering(FakeResponse(status, body))
            with self.assertRaises(LlmRequestError) as caught:
                client.generate("s", "u", SCHEMA)
            self.assertIn(str(status), str(caught.exception))
            self.assertIn("credit balance is too low", str(caught.exception))
            self.assertNotIn("secret-key", str(caught.exception))

    def test_client_error_with_an_unreadable_body(self):
        client, _ = clientAnswering(FakeResponse(401, badJson=True))
        with self.assertRaises(LlmRequestError):
            client.generate("s", "u", SCHEMA)

    def test_a_refusal_is_reported_as_blocked(self):
        client, _ = clientAnswering(FakeResponse(200, message(text("I can't help with that."), stopReason="refusal")))
        with self.assertRaises(LlmBlockedError):
            client.generate("s", "u", SCHEMA)

    def test_an_answer_cut_off_at_the_output_limit_is_reported_as_truncated(self):
        client, _ = clientAnswering(FakeResponse(200, message(text('{"hints": ['), stopReason="max_tokens")))
        with self.assertRaises(LlmTruncatedError):
            client.generate("s", "u", SCHEMA)

    def test_thinking_that_used_the_whole_budget_is_also_truncated(self):
        body = message({"type": "thinking", "thinking": "...", "signature": "x"}, stopReason="max_tokens")
        client, _ = clientAnswering(FakeResponse(200, body))
        with self.assertRaises(LlmTruncatedError):
            client.generate("s", "u", SCHEMA)

    def test_an_empty_or_unreadable_answer_is_transient(self):
        for response in (FakeResponse(200, message()), FakeResponse(200, message(text("  "))), FakeResponse(200, {}), FakeResponse(200, badJson=True)):
            client, _ = clientAnswering(response)
            with self.assertRaises(TransientLlmError):
                client.generate("s", "u", SCHEMA)


class EnvironmentTests(unittest.TestCase):
    def test_only_the_key_is_required_and_the_rest_defaults(self):
        client = clientFromEnvironment({"ANTHROPIC_API_KEY": "k"})
        self.assertEqual((client.model, client.effort), ("claude-opus-5-5", "high"))

    def test_model_and_effort_can_be_overridden(self):
        client = clientFromEnvironment({"ANTHROPIC_API_KEY": "k", "ANTHROPIC_MODEL": "claude-sonnet-5-5", "ANTHROPIC_EFFORT": "medium"})
        self.assertEqual((client.model, client.effort), ("claude-sonnet-5-5", "medium"))

    def test_a_missing_or_blank_key_is_an_error_that_names_the_variable(self):
        for environ in ({}, {"ANTHROPIC_API_KEY": "  "}):
            with self.assertRaises(LlmConfigurationError) as caught:
                clientFromEnvironment(environ)
            self.assertIn("ANTHROPIC_API_KEY", str(caught.exception))

    def test_a_bad_effort_is_an_error_that_names_the_variable(self):
        with self.assertRaises(LlmConfigurationError) as caught:
            clientFromEnvironment({"ANTHROPIC_API_KEY": "k", "ANTHROPIC_EFFORT": "turbo"})
        self.assertIn("ANTHROPIC_EFFORT", str(caught.exception))


class ProviderChoiceTests(unittest.TestCase):
    def test_anthropic_is_the_default_provider(self):
        client = createClientFromEnvironment({"ANTHROPIC_API_KEY": "k"})
        self.assertEqual(client.model, "claude-opus-5-5")

    def test_gemini_can_still_be_chosen(self):
        client = createClientFromEnvironment({"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "k", "GEMINI_MODEL": "some-gemini"})
        self.assertEqual(client.model, "some-gemini")

    def test_the_provider_name_is_case_insensitive_and_unknown_ones_are_refused(self):
        self.assertEqual(createClientFromEnvironment({"LLM_PROVIDER": " Anthropic ", "ANTHROPIC_API_KEY": "k"}).model, "claude-opus-5-5")
        with self.assertRaises(LlmConfigurationError) as caught:
            createClientFromEnvironment({"LLM_PROVIDER": "openai"})
        self.assertIn("LLM_PROVIDER", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
