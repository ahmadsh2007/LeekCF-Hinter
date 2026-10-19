import os
import requests
from src.services.llm.errors import (
    LlmBlockedError,
    LlmConfigurationError,
    LlmRequestError,
    LlmTruncatedError,
    TransientLlmError,
)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "high"
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
# A hard limit on thinking plus the answer. Five short hints are about 1.5k tokens; the rest is room for thinking.
MAX_OUTPUT_TOKENS = 16000
REQUEST_TIMEOUT_SECONDS = 600
# USD per million tokens (input, output): the standard prices on https://platform.claude.com/docs/en/about-claude/pricing,
# read on 2026-10-19. Only used for the estimate printed after a run, never for any decision.
PRICES_PER_MTOK = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-fable-5-1": (10.0, 50.0),
    "claude-sonnet-5-5": (2.0, 10.0),
}

class AnthropicClient:
    """
    The Claude Messages API over plain HTTPS. Opus 5.5 always thinks (adaptive thinking cannot be switched off), and
    `effort` controls how much; thinking tokens are billed as output tokens. Returns the model's JSON text.
    """
    def __init__(self, apiKey: str, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT, session=None):
        if effort not in EFFORT_LEVELS:
            raise LlmConfigurationError(f"ANTHROPIC_EFFORT must be one of {', '.join(EFFORT_LEVELS)}, not '{effort}'.")
        self.apiKey = apiKey
        self.model = model
        self.effort = effort
        self.session = session or requests.Session()
        self.requests = 0
        self.inputTokens = 0
        self.outputTokens = 0

    def generate(self, system: str, user: str, responseSchema: dict) -> str:
        body = {
            "model": self.model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": responseSchema},
            },
        }
        try:
            response = self.session.post(
                API_URL,
                headers={"x-api-key": self.apiKey, "anthropic-version": API_VERSION, "content-type": "application/json"},
                json=body,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as e:
            raise TransientLlmError(f"Network error ({type(e).__name__}) calling the Claude API: {e}") from e

        status = response.status_code
        if status in (408, 429) or status >= 500:
            raise TransientLlmError(f"Claude API answered HTTP {status}")
        if status != 200:
            raise LlmRequestError(f"Claude API answered HTTP {status}: {self.errorMessage(response)}")

        try:
            data = response.json()
        except ValueError as e:
            raise TransientLlmError("Claude API answered with something that is not JSON") from e
        return self.extractText(data)

    @staticmethod
    def errorMessage(response) -> str:
        try:
            return response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            return "no error message in the response"

    def extractText(self, data: dict) -> str:
        usage = data.get("usage") or {}
        # Counted before anything else: a refused or cut-off answer is billed too.
        self.requests += 1
        self.inputTokens += usage.get("input_tokens", 0)
        self.outputTokens += usage.get("output_tokens", 0)

        stopReason = data.get("stop_reason")
        if stopReason == "refusal":
            raise LlmBlockedError("The model refused this problem (stop_reason: refusal).")

        # Thinking blocks are not part of the answer; only text blocks are.
        text = "".join(block.get("text", "") for block in data.get("content") or [] if block.get("type") == "text")
        if stopReason == "max_tokens":
            raise LlmTruncatedError(f"The answer was cut off at {MAX_OUTPUT_TOKENS} output tokens (thinking included).")
        if not text.strip():
            raise TransientLlmError("Claude API returned an empty answer")
        return text

    def usageSummary(self) -> str:
        summary = f"{self.requests} request(s), {self.inputTokens:,} input + {self.outputTokens:,} output tokens"
        prices = PRICES_PER_MTOK.get(self.model)
        if prices:
            cost = (self.inputTokens * prices[0] + self.outputTokens * prices[1]) / 1_000_000
            summary += f", about ${cost:,.2f} at {self.model} list prices"
        return summary

def clientFromEnvironment(environ=None) -> AnthropicClient:
    environ = os.environ if environ is None else environ
    apiKey = (environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not apiKey:
        raise LlmConfigurationError("ANTHROPIC_API_KEY is not set (put it in the env file next to the Supabase keys).")
    model = (environ.get("ANTHROPIC_MODEL") or "").strip() or DEFAULT_MODEL
    effort = (environ.get("ANTHROPIC_EFFORT") or "").strip().lower() or DEFAULT_EFFORT
    return AnthropicClient(apiKey, model, effort)
