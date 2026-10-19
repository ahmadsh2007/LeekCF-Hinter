import os
from src.services.llm import anthropicClient, geminiClient
from src.services.llm.errors import LlmConfigurationError

def createClientFromEnvironment(environ=None):
    """LLM_PROVIDER picks the model provider: 'anthropic' (the default, Claude Opus 5.5 at high effort) or 'gemini'."""
    environ = os.environ if environ is None else environ
    provider = (environ.get("LLM_PROVIDER") or "anthropic").strip().lower()
    if provider == "anthropic":
        return anthropicClient.clientFromEnvironment(environ)
    if provider == "gemini":
        return geminiClient.clientFromEnvironment(environ)
    raise LlmConfigurationError(f"LLM_PROVIDER must be 'anthropic' or 'gemini', not '{provider}'.")
