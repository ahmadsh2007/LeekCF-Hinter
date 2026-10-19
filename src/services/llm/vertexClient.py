import datetime
import time
from src.services.llm.errors import LlmConfigurationError, LlmRequestError, TransientLlmError
from src.services.llm.geminiClient import THINKING_LEVELS, GeminiClient

DEFAULT_LOCATION = "global"
DEFAULT_MODEL = "gemini-4-argon"
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
# Gemini 4 Argon's list price per million tokens (input, output) is $2 / $10 through this date and $4 / $20 after it
# (https://ai.google.dev/gemini-api/docs/pricing, read 2026-10-19). That is the AI Studio price; Vertex's may differ,
# so the figure printed after a run is only an estimate.
ARGON_INTRODUCTORY_PRICE_ENDS = datetime.date(2026, 11, 30)

def loadApplicationDefaultCredentials():
    import google.auth
    return google.auth.default(scopes=SCOPES)

def newTransportRequest():
    from google.auth.transport.requests import Request
    return Request()

class AdcTokenProvider:
    """
    Short-lived OAuth tokens from Google's Application Default Credentials: a service account key file named by
    GOOGLE_APPLICATION_CREDENTIALS, or `gcloud auth application-default login`. Loaded on first use, refreshed when
    the token has expired.
    """
    def __init__(self, loadCredentials=None, requestFactory=None):
        self.loadCredentials = loadCredentials or loadApplicationDefaultCredentials
        self.requestFactory = requestFactory or newTransportRequest
        self.credentials = None
        self.projectId = None

    def ensureLoaded(self) -> None:
        if self.credentials is not None:
            return
        from google.auth import exceptions as googleExceptions
        try:
            self.credentials, self.projectId = self.loadCredentials()
        except googleExceptions.DefaultCredentialsError as e:
            raise LlmConfigurationError(
                "No Google credentials found. Set GOOGLE_APPLICATION_CREDENTIALS to the path of a service account key "
                f"file (role: Vertex AI User), or run `gcloud auth application-default login`. ({e})"
            ) from e

    def token(self) -> str:
        self.ensureLoaded()
        if not self.credentials.valid:
            from google.auth import exceptions as googleExceptions
            try:
                self.credentials.refresh(self.requestFactory())
            except googleExceptions.TransportError as e:
                raise TransientLlmError(f"Could not reach Google to sign in: {e}") from e
            except googleExceptions.RefreshError as e:
                raise LlmRequestError(f"Google rejected the credentials: {e}") from e
        return self.credentials.token

    def project(self) -> str | None:
        self.ensureLoaded()
        return self.projectId

class VertexGeminiClient(GeminiClient):
    """The same Gemini request as AI Studio, sent to Vertex AI and paid by the Google Cloud project (its free-trial credit)."""
    def __init__(self, project: str, location: str, model: str, tokenProvider, thinkingLevel: str | None = None,
                 session=None, sleep=time.sleep, today=datetime.date.today):
        super().__init__("", model, session=session, thinkingLevel=thinkingLevel, sleep=sleep)
        self.project = project
        self.location = location
        self.tokenProvider = tokenProvider
        self.today = today

    def endpoint(self) -> str:
        host = "aiplatform.googleapis.com" if self.location == "global" else f"{self.location}-aiplatform.googleapis.com"
        return (f"https://{host}/v1/projects/{self.project}/locations/{self.location}"
                f"/publishers/google/models/{self.model}:generateContent")

    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.tokenProvider.token()}", "Content-Type": "application/json"}

    def estimatedCostUsd(self) -> float | None:
        if self.model != DEFAULT_MODEL:
            return None
        inputPrice, outputPrice = (2.0, 10.0) if self.today() <= ARGON_INTRODUCTORY_PRICE_ENDS else (4.0, 20.0)
        # Thinking tokens are billed as output.
        return (self.inputTokens * inputPrice + (self.outputTokens + self.thinkingTokens) * outputPrice) / 1_000_000

    def usageSummary(self) -> str:
        summary = super().usageSummary()
        cost = self.estimatedCostUsd()
        if cost is not None:
            summary += f", estimate ${cost:,.2f} at AI Studio list prices (Vertex's price may differ)"
        return summary

def clientFromEnvironment(environ=None, tokenProvider=None) -> VertexGeminiClient:
    import os
    environ = os.environ if environ is None else environ
    tokenProvider = tokenProvider or AdcTokenProvider()

    project = (environ.get("VERTEX_PROJECT") or environ.get("GOOGLE_CLOUD_PROJECT") or "").strip() or tokenProvider.project()
    if not project:
        raise LlmConfigurationError("VERTEX_PROJECT is not set (the id of the Google Cloud project that holds the free-trial credit).")
    location = (environ.get("VERTEX_LOCATION") or "").strip() or DEFAULT_LOCATION
    model = (environ.get("VERTEX_MODEL") or "").strip() or DEFAULT_MODEL
    thinkingLevel = (environ.get("VERTEX_THINKING_LEVEL") or "").strip().lower() or None
    if thinkingLevel is not None and thinkingLevel not in THINKING_LEVELS:
        raise LlmConfigurationError(f"VERTEX_THINKING_LEVEL must be one of {', '.join(THINKING_LEVELS)}, not '{thinkingLevel}'.")
    return VertexGeminiClient(project, location, model, tokenProvider, thinkingLevel)
