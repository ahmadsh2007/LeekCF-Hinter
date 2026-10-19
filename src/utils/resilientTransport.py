import time
import httpx

# Pauses between attempts (seconds). The request is sent again after each pause, so a short outage is ridden out.
DEFAULT_WAITS = (1, 3, 8, 20)
# A gateway in front of the database answering with these means "try again", not "your request is wrong".
RETRY_STATUSES = (502, 503, 504)

class RetryingTransport(httpx.BaseTransport):
    """
    Wraps an httpx transport and repeats a request after a gateway error (502/503/504) or a dropped connection.
    Everything else, including every real error answer (400, 401, 404, 409, 429, 500), goes straight to the caller.
    The database workers only send requests that are safe to repeat (reads, upserts, guarded updates, deletes).
    """
    def __init__(self, inner: httpx.BaseTransport, waits=DEFAULT_WAITS, sleep=time.sleep):
        self.inner = inner
        self.waits = waits
        self.sleep = sleep

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        for wait in self.waits:
            try:
                response = self.inner.handle_request(request)
            except httpx.TransportError:
                self.sleep(wait)
                continue
            if response.status_code not in RETRY_STATUSES:
                return response
            response.close()
            self.sleep(wait)
        return self.inner.handle_request(request)

    def close(self) -> None:
        self.inner.close()
