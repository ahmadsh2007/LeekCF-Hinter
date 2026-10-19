import unittest

import requests

from src.services.llm.geminiClient import (
    GeminiClient,
    LlmBlockedError,
    LlmConfigurationError,
    LlmRequestError,
    TransientLlmError,
    clientFromEnvironment,
)

SCHEMA = {
    "type": "object",
    "properties": {"hints": {"type": "array", "items": {"type": "object", "properties": {"level": {"type": "integer"}}, "additionalProperties": False}}},
    "required": ["hints"],
    "additionalProperties": False,
}
GEMINI_SCHEMA = {
    "type": "OBJECT",
    "properties": {"hints": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"level": {"type": "INTEGER"}}}}},
    "required": ["hints"],
}


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
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def answer(*texts, finishReason="STOP"):
    return {"candidates": [{"content": {"parts": [{"text": text} for text in texts]}, "finishReason": finishReason}]}

def clientAnswering(response, **kwargs):
    session = FakeSession(response)
    sleeps = []
    client = GeminiClient("secret-key", "some-model", session=session, sleep=sleeps.append, **kwargs)
    client.sleeps = sleeps
    return client, session


class RequestShapeTests(unittest.TestCase):
    def test_posts_to_generate_content_with_the_key_in_a_header(self):
        client, session = clientAnswering(FakeResponse(200, answer("{}")))
        client.generate("SYSTEM", "USER", SCHEMA)

        call = session.calls[0]
        self.assertEqual(call["url"], "https://generativelanguage.googleapis.com/v1beta/models/some-model:generateContent")
        self.assertEqual(call["headers"]["x-goog-api-key"], "secret-key")
        self.assertNotIn("secret-key", call["url"])

    def test_body_carries_the_prompts_and_asks_for_schema_constrained_json(self):
        client, session = clientAnswering(FakeResponse(200, answer("{}")))
        client.generate("SYSTEM", "USER", SCHEMA)

        body = session.calls[0]["json"]
        self.assertEqual(body["systemInstruction"], {"parts": [{"text": "SYSTEM"}]})
        self.assertEqual(body["contents"], [{"role": "user", "parts": [{"text": "USER"}]}])
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        # Gemini's dialect: upper-case type names, and no additionalProperties
        self.assertEqual(body["generationConfig"]["responseSchema"], GEMINI_SCHEMA)
        self.assertIn("temperature", body["generationConfig"])

    def test_model_name_is_exposed_for_the_database_record(self):
        client, _ = clientAnswering(FakeResponse())
        self.assertEqual(client.model, "some-model")


class ResponseTests(unittest.TestCase):
    def test_text_parts_are_joined(self):
        client, _ = clientAnswering(FakeResponse(200, answer('{"hints":', "[]}")))
        self.assertEqual(client.generate("s", "u", SCHEMA), '{"hints":[]}')

    def test_a_truncated_answer_is_returned_for_the_validator_to_judge(self):
        client, _ = clientAnswering(FakeResponse(200, answer('{"hints": [', finishReason="MAX_TOKENS")))
        self.assertEqual(client.generate("s", "u", SCHEMA), '{"hints": [')


class ErrorTests(unittest.TestCase):
    def test_rate_limits_server_errors_and_network_problems_are_transient(self):
        for response in (FakeResponse(429, {}), FakeResponse(500, {}), FakeResponse(503, {}),
                         requests.ConnectionError("down"), requests.Timeout("slow")):
            client, _ = clientAnswering(response)
            with self.assertRaises(TransientLlmError, msg=repr(response)):
                client.generate("s", "u", SCHEMA)

    def test_client_errors_name_the_api_message_and_never_the_key(self):
        body = {"error": {"code": 404, "message": "models/some-model is not found", "status": "NOT_FOUND"}}
        for status in (400, 401, 403, 404):
            client, _ = clientAnswering(FakeResponse(status, body))
            with self.assertRaises(LlmRequestError) as caught:
                client.generate("s", "u", SCHEMA)
            self.assertIn(str(status), str(caught.exception))
            self.assertIn("models/some-model is not found", str(caught.exception))
            self.assertNotIn("secret-key", str(caught.exception))

    def test_client_error_with_an_unreadable_body(self):
        client, _ = clientAnswering(FakeResponse(403, badJson=True))
        with self.assertRaises(LlmRequestError):
            client.generate("s", "u", SCHEMA)

    def test_a_blocked_prompt_is_reported_as_blocked(self):
        client, _ = clientAnswering(FakeResponse(200, {"promptFeedback": {"blockReason": "SAFETY"}}))
        with self.assertRaises(LlmBlockedError):
            client.generate("s", "u", SCHEMA)

    def test_a_blocked_answer_is_reported_as_blocked(self):
        for reason in ("SAFETY", "RECITATION", "PROHIBITED_CONTENT"):
            client, _ = clientAnswering(FakeResponse(200, answer("partial", finishReason=reason)))
            with self.assertRaises(LlmBlockedError, msg=reason):
                client.generate("s", "u", SCHEMA)

    def test_an_empty_or_unreadable_answer_is_transient(self):
        for response in (FakeResponse(200, {"candidates": []}), FakeResponse(200, {}), FakeResponse(200, badJson=True),
                         FakeResponse(200, answer(""))):
            client, _ = clientAnswering(response)
            with self.assertRaises(TransientLlmError):
                client.generate("s", "u", SCHEMA)


class ThinkingTests(unittest.TestCase):
    def test_thinking_is_left_to_the_model_by_default(self):
        client, session = clientAnswering(FakeResponse(200, answer("{}")))
        client.generate("s", "u", SCHEMA)
        self.assertNotIn("thinkingConfig", session.calls[0]["json"]["generationConfig"])

    def test_a_thinking_level_can_be_requested(self):
        client, session = clientAnswering(FakeResponse(200, answer("{}")), thinkingLevel="high")
        client.generate("s", "u", SCHEMA)
        self.assertEqual(session.calls[0]["json"]["generationConfig"]["thinkingConfig"], {"thinkingLevel": "high"})

    def test_an_unknown_thinking_level_is_refused_before_any_request(self):
        with self.assertRaises(LlmConfigurationError):
            GeminiClient("k", "m", thinkingLevel="extreme", session=FakeSession(FakeResponse()))

    def test_thought_parts_are_not_part_of_the_answer(self):
        body = {"candidates": [{"content": {"parts": [{"text": "let me think", "thought": True}, {"text": '{"hints": []}'}]}, "finishReason": "STOP"}]}
        client, _ = clientAnswering(FakeResponse(200, body))
        self.assertEqual(client.generate("s", "u", SCHEMA), '{"hints": []}')


class UsageTests(unittest.TestCase):
    def test_tokens_including_thinking_are_counted_and_summarised(self):
        body = answer("{}")
        body["usageMetadata"] = {"promptTokenCount": 2000, "candidatesTokenCount": 600, "thoughtsTokenCount": 1500}
        client, _ = clientAnswering(FakeResponse(200, body))
        client.generate("s", "u", SCHEMA)
        client.generate("s", "u", SCHEMA)
        self.assertEqual((client.requests, client.inputTokens, client.outputTokens, client.thinkingTokens), (2, 4000, 1200, 3000))
        summary = client.usageSummary()
        for fragment in ("2 request(s)", "4,000 input", "1,200 output", "3,000 thinking"):
            self.assertIn(fragment, summary)

    def test_a_response_without_usage_metadata_is_fine(self):
        client, _ = clientAnswering(FakeResponse(200, answer("{}")))
        client.generate("s", "u", SCHEMA)
        self.assertEqual(client.inputTokens, 0)


class RateLimitRetryTests(unittest.TestCase):
    class Sequence:
        def __init__(self, *responses):
            self.responses = list(responses)
            self.calls = []

        def post(self, url, headers=None, json=None, timeout=None):
            self.calls.append(url)
            return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]

    def clientWith(self, *responses):
        sleeps = []
        client = GeminiClient("k", "m", session=self.Sequence(*responses), sleep=sleeps.append)
        return client, sleeps

    def test_a_per_minute_limit_is_waited_out_and_retried(self):
        client, sleeps = self.clientWith(FakeResponse(429, {}), FakeResponse(200, answer("{}")))
        self.assertEqual(client.generate("s", "u", SCHEMA), "{}")
        self.assertEqual(sleeps, [20])

    def test_an_overloaded_model_is_retried_too(self):
        client, sleeps = self.clientWith(FakeResponse(503, {}), FakeResponse(503, {}), FakeResponse(200, answer("{}")))
        self.assertEqual(client.generate("s", "u", SCHEMA), "{}")
        self.assertEqual(sleeps, [20, 40])

    def test_after_three_waits_it_gives_up_as_transient(self):
        client, sleeps = self.clientWith(FakeResponse(429, {}))
        with self.assertRaises(TransientLlmError):
            client.generate("s", "u", SCHEMA)
        self.assertEqual(sleeps, [20, 40, 80])
        self.assertEqual(len(client.session.calls), 4)

    def test_other_server_errors_are_not_retried_here(self):
        client, sleeps = self.clientWith(FakeResponse(500, {}))
        with self.assertRaises(TransientLlmError):
            client.generate("s", "u", SCHEMA)
        self.assertEqual(sleeps, [])


class EnvironmentTests(unittest.TestCase):
    def test_builds_a_client_from_the_two_variables(self):
        client = clientFromEnvironment({"GEMINI_API_KEY": "k", "GEMINI_MODEL": "m"})
        self.assertEqual(client.model, "m")

    def test_both_variables_are_required_and_the_error_says_which(self):
        with self.assertRaises(LlmConfigurationError) as noKey:
            clientFromEnvironment({"GEMINI_MODEL": "m"})
        self.assertIn("GEMINI_API_KEY", str(noKey.exception))
        with self.assertRaises(LlmConfigurationError) as noModel:
            clientFromEnvironment({"GEMINI_API_KEY": "k"})
        self.assertIn("GEMINI_MODEL", str(noModel.exception))

    def test_the_thinking_level_comes_from_the_environment_when_set(self):
        client = clientFromEnvironment({"GEMINI_API_KEY": "k", "GEMINI_MODEL": "m", "GEMINI_THINKING_LEVEL": "high"})
        self.assertEqual(client.thinkingLevel, "high")
        self.assertIsNone(clientFromEnvironment({"GEMINI_API_KEY": "k", "GEMINI_MODEL": "m"}).thinkingLevel)

    def test_blank_values_count_as_missing(self):
        with self.assertRaises(LlmConfigurationError):
            clientFromEnvironment({"GEMINI_API_KEY": "  ", "GEMINI_MODEL": "m"})

    def test_a_configuration_error_is_a_request_error(self):
        self.assertTrue(issubclass(LlmConfigurationError, LlmRequestError))


if __name__ == "__main__":
    unittest.main()
