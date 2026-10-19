import unittest

import httpx

from src.utils.retry import DEFAULT_WAITS, retryOnNetworkErrors


class Flaky:
    def __init__(self, failures, error=None):
        self.failures = failures
        self.error = error or httpx.ConnectError("Connection reset by peer")
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return f"ok after {self.calls}"


class RetryTests(unittest.TestCase):
    def test_a_call_that_works_is_not_retried_or_delayed(self):
        sleeps = []
        flaky = Flaky(0)
        self.assertEqual(retryOnNetworkErrors(flaky, sleep=sleeps.append), "ok after 1")
        self.assertEqual(sleeps, [])

    def test_network_errors_are_retried_after_growing_pauses(self):
        sleeps = []
        flaky = Flaky(2)
        self.assertEqual(retryOnNetworkErrors(flaky, sleep=sleeps.append), "ok after 3")
        self.assertEqual(sleeps, list(DEFAULT_WAITS[:2]))

    def test_it_gives_up_after_the_last_pause_and_raises_the_network_error(self):
        sleeps = []
        flaky = Flaky(99)
        with self.assertRaises(httpx.ConnectError):
            retryOnNetworkErrors(flaky, sleep=sleeps.append)
        self.assertEqual(flaky.calls, len(DEFAULT_WAITS) + 1)
        self.assertEqual(sleeps, list(DEFAULT_WAITS))

    def test_timeouts_and_dropped_connections_count_as_network_errors(self):
        for error in (httpx.ReadTimeout("slow"), httpx.RemoteProtocolError("dropped"), httpx.ReadError("reset")):
            flaky = Flaky(1, error)
            self.assertEqual(retryOnNetworkErrors(flaky, sleep=lambda s: None), "ok after 2")

    def test_other_errors_are_never_retried(self):
        flaky = Flaky(99, ValueError("a bug, not a blip"))
        with self.assertRaises(ValueError):
            retryOnNetworkErrors(flaky, sleep=lambda s: None)
        self.assertEqual(flaky.calls, 1)

    def test_custom_pauses(self):
        sleeps = []
        retryOnNetworkErrors(Flaky(1), waits=(7,), sleep=sleeps.append)
        self.assertEqual(sleeps, [7])


if __name__ == "__main__":
    unittest.main()
