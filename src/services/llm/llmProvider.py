import os
from src.services.llm import anthropicClient, geminiClient, vertexClient
from src.services.llm.errors import LlmConfigurationError, LlmRequestError

PROVIDERS = ("anthropic", "gemini", "vertex")

class FallbackLlm:
    """
    Several clients in order of preference. When one fails with a request error (the credit is used up, the billing
    account was closed, the key was revoked) the next one takes over for good. Other errors (rate limits, blocked
    answers) are not a reason to switch. `model` is the model that answered last, which is what gets stored with the hints.
    """
    def __init__(self, clients: list):
        self.clients = clients
        self.index = 0

    @property
    def model(self) -> str:
        return self.clients[self.index].model

    def generate(self, system: str, user: str, schema: dict) -> str:
        while True:
            client = self.clients[self.index]
            try:
                return client.generate(system, user, schema)
            except LlmRequestError as e:
                if self.index + 1 >= len(self.clients):
                    raise
                following = self.clients[self.index + 1]
                print(f"[SWITCHING MODEL] {client.model} failed ({e}). Continuing with {following.model} from here on.")
                self.index += 1

    def usageSummary(self) -> str:
        return " | ".join(
            f"{client.model}: {client.usageSummary()}"
            for client in self.clients
            if getattr(client, "requests", 0) > 0 and hasattr(client, "usageSummary")
        )

def buildClient(name: str, environ, tokenProvider):
    if name == "anthropic":
        return anthropicClient.clientFromEnvironment(environ)
    if name == "gemini":
        return geminiClient.clientFromEnvironment(environ)
    if name == "vertex":
        return vertexClient.clientFromEnvironment(environ, tokenProvider)
    raise LlmConfigurationError(f"LLM_PROVIDER entries must be {', '.join(repr(p) for p in PROVIDERS)}, not '{name}'.")

def createClientFromEnvironment(environ=None, tokenProvider=None):
    """
    LLM_PROVIDER picks the model provider: 'anthropic' (the default, Claude Opus 5.5 at high effort), 'gemini'
    (Google AI Studio) or 'vertex' (Gemini 4 Argon on Vertex AI). A comma-separated list such as 'vertex,gemini' is a
    fallback chain: every entry is configured at start, so a mistake shows up now and not when the first one fails.
    """
    environ = os.environ if environ is None else environ
    names = [name.strip().lower() for name in (environ.get("LLM_PROVIDER") or "anthropic").split(",") if name.strip()]
    if not names:
        raise LlmConfigurationError("LLM_PROVIDER is empty.")
    clients = [buildClient(name, environ, tokenProvider) for name in names]
    return clients[0] if len(clients) == 1 else FallbackLlm(clients)
