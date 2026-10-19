import datetime
import unittest

import requests
from google.auth import exceptions as googleExceptions

from src.services.llm.errors import (
    LlmBlockedError,
    LlmConfigurationError,
    LlmRequestError,
    TransientLlmError,
)
from src.services.llm.vertexClient import (
    AdcTokenProvider,
    VertexGeminiClient,
    clientFromEnvironment,
)

SCHEMA = {"type": "object", "properties": {"hints": {"type": "array", "items": {"type": "string"}}}, "additionalProperties": False}


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.body = body

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


class FakeTokens:
    def __init__(self, project="adc-project"):
        self.count = 0
        self.projectId = project

    def token(self):
        self.count += 1
        return f"token-{self.count}"

    def project(self):
        return self.projectId


def answer(text="{}", usage=None):
    body = {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}
    if usage:
        body["usageMetadata"] = usage
    return body

def vertex(*responses, **kwargs):
    session = FakeSession(*responses)
    options = dict(project="my-proj", location="global", model="gemini-4-argon", tokenProvider=FakeTokens(), session=session, sleep=lambda s: None)
    options.update(kwargs)
    return VertexGeminiClient(**options), session


class RequestTests(unittest.TestCase):
    def test_the_global_endpoint(self):
        client, session = vertex(FakeResponse(200, answer()))
        client.generate("sys", "user", SCHEMA)
        self.assertEqual(session.calls[0]["url"],
                         "https://aiplatform.googleapis.com/v1/projects/my-proj/locations/global/publishers/google/models/gemini-4-argon:generateContent")

    def test_a_regional_endpoint(self):
        client, session = vertex(FakeResponse(200, answer()), location="europe-west4")
        client.generate("sys", "user", SCHEMA)
        self.assertEqual(session.calls[0]["url"],
                         "https://europe-west4-aiplatform.googleapis.com/v1/projects/my-proj/locations/europe-west4/publishers/google/models/gemini-4-argon:generateContent")

    def test_signs_in_with_a_fresh_bearer_token_for_every_call_and_never_sends_an_api_key(self):
        tokens = FakeTokens()
        client, session = vertex(FakeResponse(200, answer()), tokenProvider=tokens)
        client.generate("s", "u", SCHEMA)
        client.generate("s", "u", SCHEMA)
        self.assertEqual([call["headers"]["Authorization"] for call in session.calls], ["Bearer token-1", "Bearer token-2"])
        self.assertNotIn("x-goog-api-key", session.calls[0]["headers"])

    def test_the_body_is_the_gemini_body_with_the_schema_converted(self):
        client, session = vertex(FakeResponse(200, answer()), thinkingLevel="high")
        client.generate("SYSTEM", "USER", SCHEMA)
        body = session.calls[0]["json"]
        self.assertEqual(body["systemInstruction"], {"parts": [{"text": "SYSTEM"}]})
        self.assertEqual(body["contents"], [{"role": "user", "parts": [{"text": "USER"}]}])
        config = body["generationConfig"]
        self.assertEqual(config["responseMimeType"], "application/json")
        self.assertEqual(config["responseSchema"]["type"], "OBJECT")
        self.assertNotIn("additionalProperties", config["responseSchema"])
        self.assertEqual(config["thinkingConfig"], {"thinkingLevel": "high"})

    def test_the_model_name_is_exposed_for_the_database_record(self):
        client, _ = vertex(FakeResponse())
        self.assertEqual(client.model, "gemini-4-argon")


class ErrorTests(unittest.TestCase):
    def test_a_closed_billing_account_or_disabled_api_stops_the_run_with_googles_message(self):
        body = {"error": {"code": 403, "message": "Vertex AI API has not been used in project my-proj before or it is disabled."}}
        client, _ = vertex(FakeResponse(403, body))
        with self.assertRaises(LlmRequestError) as caught:
            client.generate("s", "u", SCHEMA)
        self.assertIn("403", str(caught.exception))
        self.assertIn("is disabled", str(caught.exception))

    def test_rate_limits_are_waited_out_like_with_ai_studio(self):
        sleeps = []
        client, _ = vertex(FakeResponse(429, {}), FakeResponse(200, answer("{}")), sleep=sleeps.append)
        self.assertEqual(client.generate("s", "u", SCHEMA), "{}")
        self.assertEqual(sleeps, [20])

    def test_blocked_answers_are_reported(self):
        body = {"candidates": [{"content": {"parts": [{"text": "x"}]}, "finishReason": "SAFETY"}]}
        client, _ = vertex(FakeResponse(200, body))
        with self.assertRaises(LlmBlockedError):
            client.generate("s", "u", SCHEMA)

    def test_a_network_error_is_transient(self):
        class Broken:
            def post(self, *a, **k):
                raise requests.ConnectionError("down")
        client, _ = vertex(FakeResponse(), session=Broken())
        with self.assertRaises(TransientLlmError):
            client.generate("s", "u", SCHEMA)


class SpendEstimateTests(unittest.TestCase):
    USAGE = {"promptTokenCount": 1_000_000, "candidatesTokenCount": 400_000, "thoughtsTokenCount": 600_000}

    def summary(self, today, model="gemini-4-argon"):
        client, _ = vertex(FakeResponse(200, answer("{}", self.USAGE)), model=model, today=lambda: today)
        client.generate("s", "u", SCHEMA)
        return client.usageSummary()

    def test_thinking_tokens_are_billed_as_output_at_the_introductory_price(self):
        summary = self.summary(datetime.date(2026, 11, 30))
        self.assertIn("$12.00", summary)  # 1M x $2 + (0.4M + 0.6M) x $10
        self.assertIn("600,000 thinking", summary)

    def test_the_price_doubles_from_december_first(self):
        self.assertIn("$24.00", self.summary(datetime.date(2026, 12, 1)))

    def test_it_says_the_figure_is_an_estimate(self):
        self.assertIn("estimate", self.summary(datetime.date(2026, 11, 1)).lower())

    def test_a_model_with_no_known_price_gets_no_dollar_figure(self):
        self.assertNotIn("$", self.summary(datetime.date(2026, 11, 1), model="some-other-model"))


class EnvironmentTests(unittest.TestCase):
    def test_defaults_are_argon_on_the_global_endpoint(self):
        client = clientFromEnvironment({"VERTEX_PROJECT": "p"}, tokenProvider=FakeTokens())
        self.assertEqual((client.project, client.location, client.model), ("p", "global", "gemini-4-argon"))

    def test_everything_can_be_overridden(self):
        client = clientFromEnvironment(
            {"VERTEX_PROJECT": "p", "VERTEX_LOCATION": "us-central1", "VERTEX_MODEL": "gemini-3.8-flash", "VERTEX_THINKING_LEVEL": "high"},
            tokenProvider=FakeTokens())
        self.assertEqual((client.location, client.model, client.thinkingLevel), ("us-central1", "gemini-3.8-flash", "high"))

    def test_the_project_falls_back_to_google_cloud_project_then_to_the_credentials(self):
        self.assertEqual(clientFromEnvironment({"GOOGLE_CLOUD_PROJECT": "g"}, tokenProvider=FakeTokens()).project, "g")
        self.assertEqual(clientFromEnvironment({}, tokenProvider=FakeTokens("from-credentials")).project, "from-credentials")

    def test_no_project_anywhere_is_an_error_that_names_the_variable(self):
        with self.assertRaises(LlmConfigurationError) as caught:
            clientFromEnvironment({}, tokenProvider=FakeTokens(None))
        self.assertIn("VERTEX_PROJECT", str(caught.exception))


class FakeCredentials:
    def __init__(self, valid=False, refreshError=None):
        self.valid = valid
        self.token = "stale" if valid else None
        self.refreshes = 0
        self.refreshError = refreshError

    def refresh(self, request):
        self.refreshes += 1
        if self.refreshError:
            raise self.refreshError
        self.valid, self.token = True, f"fresh-{self.refreshes}"


class TokenProviderTests(unittest.TestCase):
    def provider(self, credentials, project="proj"):
        loads = []
        def load():
            loads.append(1)
            return credentials, project
        provider = AdcTokenProvider(loadCredentials=load, requestFactory=lambda: object())
        provider.loads = loads
        return provider

    def test_credentials_are_loaded_once_and_only_when_first_needed(self):
        provider = self.provider(FakeCredentials())
        self.assertEqual(provider.loads, [])
        provider.token(); provider.token()
        self.assertEqual(len(provider.loads), 1)

    def test_an_expired_token_is_refreshed_and_a_valid_one_is_reused(self):
        credentials = FakeCredentials()
        provider = self.provider(credentials)
        self.assertEqual(provider.token(), "fresh-1")
        self.assertEqual(provider.token(), "fresh-1")
        self.assertEqual(credentials.refreshes, 1)
        credentials.valid = False
        self.assertEqual(provider.token(), "fresh-2")

    def test_the_project_comes_from_the_credentials(self):
        self.assertEqual(self.provider(FakeCredentials(), project="from-adc").project(), "from-adc")

    def test_missing_credentials_explain_how_to_set_them_up(self):
        def load():
            raise googleExceptions.DefaultCredentialsError("not found")
        with self.assertRaises(LlmConfigurationError) as caught:
            AdcTokenProvider(loadCredentials=load).token()
        self.assertIn("GOOGLE_APPLICATION_CREDENTIALS", str(caught.exception))

    def test_a_network_problem_while_signing_in_is_transient(self):
        provider = self.provider(FakeCredentials(refreshError=googleExceptions.TransportError("down")))
        with self.assertRaises(TransientLlmError):
            provider.token()

    def test_rejected_credentials_stop_the_run(self):
        provider = self.provider(FakeCredentials(refreshError=googleExceptions.RefreshError("invalid_grant")))
        with self.assertRaises(LlmRequestError) as caught:
            provider.token()
        self.assertIn("invalid_grant", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
