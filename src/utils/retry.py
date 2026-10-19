import time
import httpx

# Pauses between attempts after a dropped connection (seconds): the call is made once more after each pause.
DEFAULT_WAITS = (2, 5, 15)

def retryOnNetworkErrors(call, waits=DEFAULT_WAITS, sleep=time.sleep):
    """
    Runs `call`, and runs it again after each pause when the network drops (connection reset, timeout, ...).
    Only network errors are retried; any other error is a bug or a real answer and passes straight through.
    The calls given here must be safe to repeat (upserts, guarded updates, reads).
    """
    for wait in waits:
        try:
            return call()
        except httpx.TransportError:
            sleep(wait)
    return call()
