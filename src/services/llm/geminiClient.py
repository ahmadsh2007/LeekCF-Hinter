import os
import requests
from src.services.llm.errors import (  # re-exported: callers import the errors from here
    LlmBlockedError,
    LlmConfigurationError,
    LlmError,
    LlmRequestError,
    LlmTruncatedError,
    TransientLlmError,
)

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
REQUEST_TIMEOUT_SECONDS = 180
TEMPERATURE = 0.4
# Reasons for which the model refused or cut the answer for content reasons.
BLOCKED_FINISH_REASONS = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY"}

def toGeminiSchema(schema):
    """Gemini's responseSchema is an OpenAPI subset: upper-case type names and no additionalProperties."""
    if isinstance(schema, dict):
        return {
            key: (value.upper() if key == "type" and isinstance(value, str) else toGeminiSchema(value))
            for key, value in schema.items()
            if key != "additionalProperties"
        }
    if isinstance(schema, list):
        return [toGeminiSchema(item) for item in schema]
    return schema

class GeminiClient:
    """Google AI Studio (Gemini API) over plain HTTPS. Returns the model's text; judging it is the validator's job."""
    def __init__(self, apiKey: str, model: str, session=None):
        self.apiKey = apiKey
        self.model = model
        self.session = session or requests.Session()

    def generate(self, system: str, user: str, responseSchema: dict) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": TEMPERATURE,
                "responseMimeType": "application/json",
                "responseSchema": toGeminiSchema(responseSchema),
            },
        }
        try:
            response = self.session.post(
                f"{API_ROOT}/{self.model}:generateContent",
                headers={"x-goog-api-key": self.apiKey, "Content-Type": "application/json"},
                json=body,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            raise TransientLlmError(f"Network error ({type(e).__name__}) calling the Gemini API: {e}") from e

        if response.status_code == 429 or response.status_code >= 500:
            raise TransientLlmError(f"Gemini API answered HTTP {response.status_code}")
        if response.status_code != 200:
            raise LlmRequestError(f"Gemini API answered HTTP {response.status_code}: {self.errorMessage(response)}")

        try:
            data = response.json()
        except ValueError as e:
            raise TransientLlmError("Gemini API answered with something that is not JSON") from e
        return self.extractText(data)

    @staticmethod
    def errorMessage(response) -> str:
        try:
            return response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            return "no error message in the response"

    @staticmethod
    def extractText(data: dict) -> str:
        blockReason = (data.get("promptFeedback") or {}).get("blockReason")
        if blockReason:
            raise LlmBlockedError(f"The prompt was blocked ({blockReason}).")

        candidates = data.get("candidates") or []
        if not candidates:
            raise TransientLlmError("Gemini API returned no candidates")

        candidate = candidates[0]
        if candidate.get("finishReason") in BLOCKED_FINISH_REASONS:
            raise LlmBlockedError(f"The answer was blocked ({candidate['finishReason']}).")

        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)
        if not text.strip():
            raise TransientLlmError("Gemini API returned an empty answer")
        return text

def clientFromEnvironment(environ=None) -> GeminiClient:
    environ = os.environ if environ is None else environ
    apiKey = (environ.get("GEMINI_API_KEY") or "").strip()
    model = (environ.get("GEMINI_MODEL") or "").strip()
    if not apiKey:
        raise LlmConfigurationError("GEMINI_API_KEY is not set (put it in the env file next to the Supabase keys).")
    if not model:
        raise LlmConfigurationError(
            "GEMINI_MODEL is not set. There is deliberately no default: pick a model from "
            "https://ai.google.dev/gemini-api/docs/models and set GEMINI_MODEL to its id."
        )
    return GeminiClient(apiKey, model)
