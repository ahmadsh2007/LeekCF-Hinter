class LlmError(Exception):
    pass

class TransientLlmError(LlmError):
    """Rate limit, server trouble or an empty answer: trying again later may work."""

class DailyQuotaExhaustedError(TransientLlmError):
    """A free-tier model has used up today's requests. Retrying soon is pointless; `retryAfterSeconds` says when it resets."""
    def __init__(self, message: str, retryAfterSeconds: float):
        super().__init__(message)
        self.retryAfterSeconds = retryAfterSeconds

class LlmRequestError(LlmError):
    """The API rejected the request itself (bad key, no credit, unknown model, malformed request). Every call will fail."""

class LlmConfigurationError(LlmRequestError):
    """A required environment variable is missing or invalid."""

class LlmBlockedError(LlmError):
    """The model refused this particular problem for content reasons."""

class LlmTruncatedError(LlmError):
    """The answer hit the output limit before it was complete (thinking can use up the budget)."""
