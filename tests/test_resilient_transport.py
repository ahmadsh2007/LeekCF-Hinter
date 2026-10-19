import unittest

import httpx

from src.utils.resilientTransport import DEFAULT_WAITS, RetryingTransport


def clientWith(handler, waits=DEFAULT_WAITS):
    sleeps = []
    transport = RetryingTransport(httpx.MockTransport(handler), waits=waits, sleep=sleeps.append)
    return httpx.Client(transport=transport), sleeps


class Scripted:
    """A handler that answers with the next scripted status (or raises the next scripted error)."""
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome, text="<html>Bad gateway</html>" if outcome >= 500 else '{"ok": true}')


class RetryingTransportTests(unittest.TestCase):
    def test_a_normal_answer_passes_through_untouched(self):
        handler = Scripted(200)
        client, sleeps = clientWith(handler)
        self.assertEqual(client.get("https://db.test/x").status_code, 200)
        self.assertEqual((len(handler.requests), sleeps), (1, []))

    def test_gateway_errors_are_retried_after_growing_pauses(self):
        for status in (502, 503, 504):
            handler = Scripted(status, status, 200)
            client, sleeps = clientWith(handler)
            self.assertEqual(client.get("https://db.test/x").status_code, 200, status)
            self.assertEqual(sleeps, list(DEFAULT_WAITS[:2]), status)

    def test_dropped_connections_and_timeouts_are_retried_too(self):
        for error in (httpx.ConnectError("reset"), httpx.ReadTimeout("slow"), httpx.RemoteProtocolError("dropped")):
            client, sleeps = clientWith(Scripted(error, 200))
            self.assertEqual(client.get("https://db.test/x").status_code, 200)
            self.assertEqual(sleeps, [DEFAULT_WAITS[0]])

    def test_when_it_never_recovers_the_caller_sees_the_real_error_status(self):
        handler = Scripted(502)
        client, sleeps = clientWith(handler)
        self.assertEqual(client.get("https://db.test/x").status_code, 502)
        self.assertEqual(len(handler.requests), len(DEFAULT_WAITS) + 1)
        self.assertEqual(sleeps, list(DEFAULT_WAITS))

    def test_a_network_error_that_never_recovers_is_raised(self):
        client, _ = clientWith(Scripted(httpx.ConnectError("reset")))
        with self.assertRaises(httpx.ConnectError):
            client.get("https://db.test/x")

    def test_real_answers_are_never_retried(self):
        for status in (400, 401, 403, 404, 409, 429, 500):
            handler = Scripted(status)
            client, sleeps = clientWith(handler)
            self.assertEqual(client.get("https://db.test/x").status_code, status)
            self.assertEqual((len(handler.requests), sleeps), (1, []), status)

    def test_a_retried_write_sends_the_same_body_again(self):
        handler = Scripted(502, 201)
        client, _ = clientWith(handler)
        response = client.post("https://db.test/rest/v1/hints", json={"problem_id": "1_A", "hint_level": 1})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(handler.requests[0].content, handler.requests[1].content)
        self.assertIn(b"1_A", handler.requests[1].content)

    def test_custom_pauses(self):
        client, sleeps = clientWith(Scripted(503, 200), waits=(7,))
        client.get("https://db.test/x")
        self.assertEqual(sleeps, [7])


if __name__ == "__main__":
    unittest.main()
