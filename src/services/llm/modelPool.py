import time
from src.services.llm.errors import DailyQuotaExhaustedError, TransientLlmError

MAX_BLOCK_SECONDS = 24 * 3600

class GeminiModelPool:
    """
    Several Gemini models in order of preference. Free-tier models each have a small daily quota, so when the best one is
    used up the next one carries on, and the best one is tried again once its quota has reset. A model that is merely
    overloaded is skipped for that call only. `model` is the model that answered last, which is what is stored with the hints.
    """
    def __init__(self, clients: list, now=time.time):
        self.clients = clients
        self.now = now
        self.blockedUntil: dict[str, float] = {}
        self.lastAnswering = clients[0]

    @property
    def model(self) -> str:
        return self.lastAnswering.model

    def generate(self, system: str, user: str, schema: dict) -> str:
        lastTransient: TransientLlmError | None = None
        for client in self.clients:
            if self.blockedUntil.get(client.model, 0) > self.now():
                continue
            try:
                result = client.generate(system, user, schema)
            except DailyQuotaExhaustedError as e:
                self.blockedUntil[client.model] = self.now() + min(e.retryAfterSeconds, MAX_BLOCK_SECONDS)
                print(f"[MODEL OUT OF QUOTA] {client.model}: skipping it for {min(e.retryAfterSeconds, MAX_BLOCK_SECONDS) / 3600:.1f} h.")
                lastTransient = lastTransient or e
                continue
            except TransientLlmError as e:
                lastTransient = e
                continue
            self.lastAnswering = client
            return result

        waits = [until - self.now() for until in self.blockedUntil.values() if until > self.now()]
        if lastTransient is None or (waits and len(waits) == len(self.clients)):
            raise DailyQuotaExhaustedError("Every model in the pool has used up its daily quota", min(waits) if waits else 3600)
        raise lastTransient

    def usageSummary(self) -> str:
        return " | ".join(
            f"{client.model}: {client.usageSummary()}"
            for client in self.clients
            if getattr(client, "requests", 0) > 0
        )
