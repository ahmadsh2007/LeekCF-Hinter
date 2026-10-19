import unittest
from types import SimpleNamespace

from src.services.scraper.errors import ScrapingValidationError, TransientScrapeError
from src.services.scraper.mainChecker import (
    MAX_CONSECUTIVE_TRANSIENT_FAILURES,
    MAX_SCRAPE_ATTEMPTS,
    buildTransientFailureUpdate,
    checkAndProcessProblem,
)
from tests.fixtures import buildPage


class FakeQuery:
    """Records one supabase-py style call chain; select() returns the client's problems."""

    def __init__(self, client, tableName):
        self.client = client
        self.tableName = tableName
        self.operation = "select"
        self.payload = None
        self.filters = []
        self.orderColumns = []
        self.limitCount = None

    def select(self, columns):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def order(self, column):
        self.orderColumns.append(column)
        return self

    def limit(self, count):
        self.limitCount = count
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = payload
        return self

    def upsert(self, payload):
        self.operation = "upsert"
        self.payload = payload
        return self

    def execute(self):
        self.client.calls.append(self)
        if self.operation == "upsert" and self.tableName in self.client.failingUpsertTables:
            raise RuntimeError(f"boom on {self.tableName}")
        data = self.client.problems if self.operation == "select" else []
        return SimpleNamespace(data=data)


class FakeClient:
    def __init__(self, problems, failingUpsertTables=()):
        self.problems = problems
        self.calls = []
        self.failingUpsertTables = set(failingUpsertTables)

    def table(self, tableName):
        return FakeQuery(self, tableName)

    def writesTo(self, tableName, operation):
        return [call for call in self.calls if call.tableName == tableName and call.operation == operation]

    def statusUpdates(self) -> list:
        """(problem id, payload) for every update to the problems table."""
        return [(dict(call.filters)["id"], call.payload) for call in self.writesTo("problems", "update")]


def problemRows(count: int, scrapeAttempts: int = 0) -> list:
    return [
        {"id": f"1800_{index}", "contest_id": 1800, "index": index, "scrape_attempts": scrapeAttempts}
        for index in "ABCDEFGHIJ"[:count]
    ]


def scripted(outcomes: list):
    """A fetchPage stand-in that returns or raises the next scripted outcome and records its calls."""
    remaining = iter(outcomes)
    calls = []

    def fetchPage(contestId, index):
        calls.append((contestId, index))
        outcome = next(remaining)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    fetchPage.calls = calls
    return fetchPage


def runBatch(client, fetchPage, limit=1000, delaySeconds=0.0):
    sleeps = []
    counts = checkAndProcessProblem(client, limit=limit, delaySeconds=delaySeconds, fetchPage=fetchPage, sleep=sleeps.append)
    return counts, sleeps


class BuildTransientFailureUpdateTests(unittest.TestCase):
    def test_counts_the_attempt_and_keeps_the_problem_discoverable(self):
        update = buildTransientFailureUpdate(0, "HTTP 429")
        self.assertEqual(update["scrape_attempts"], 1)
        self.assertEqual(update["last_error"], "HTTP 429")
        self.assertEqual(update["updated_at"], "now()")
        self.assertNotIn("stage_status", update)

    def test_gives_up_on_the_last_allowed_attempt(self):
        update = buildTransientFailureUpdate(MAX_SCRAPE_ATTEMPTS - 1, "HTTP 429")
        self.assertEqual(update["scrape_attempts"], MAX_SCRAPE_ATTEMPTS)
        self.assertEqual(update["stage_status"], "FAILED")


class SelectionTests(unittest.TestCase):
    def test_selects_discovered_problems_least_attempted_first_up_to_the_limit(self):
        client = FakeClient([])
        runBatch(client, scripted([]), limit=250)
        selectCall = client.calls[0]
        self.assertEqual(selectCall.tableName, "problems")
        self.assertIn(("stage_status", "DISCOVERED"), selectCall.filters)
        self.assertEqual(selectCall.orderColumns, ["scrape_attempts", "id"])
        self.assertEqual(selectCall.limitCount, 250)

    def test_nothing_to_do_returns_zero_counts_and_never_waits(self):
        counts, sleeps = runBatch(FakeClient([]), scripted([]), delaySeconds=2.0)
        self.assertEqual(counts, {"scraped": 0, "failed": 0, "retry_later": 0})
        self.assertEqual(sleeps, [])


class SuccessTests(unittest.TestCase):
    def test_stores_specs_then_samples_and_only_then_marks_the_problem_scraped(self):
        client = FakeClient(problemRows(1))
        counts, _ = runBatch(client, scripted([buildPage()]))

        self.assertEqual(counts["scraped"], 1)
        self.assertEqual(
            [(call.tableName, call.operation) for call in client.calls],
            [("problems", "select"), ("problem_specifications", "upsert"), ("sample_tests", "upsert"), ("problems", "update")],
        )

    def test_payloads_are_tagged_with_the_problem_id_and_carry_the_hash(self):
        client = FakeClient(problemRows(1))
        runBatch(client, scripted([buildPage()]))

        specs = client.writesTo("problem_specifications", "upsert")[0].payload
        self.assertEqual(specs["problem_id"], "1800_A")
        self.assertRegex(specs["statement_hash"], r"^[0-9a-f]{64}$")
        samples = client.writesTo("sample_tests", "upsert")[0].payload
        self.assertEqual([sample["problem_id"] for sample in samples], ["1800_A"])

    def test_a_problem_without_samples_is_scraped_without_writing_an_empty_samples_request(self):
        client = FakeClient(problemRows(1))
        counts, _ = runBatch(client, scripted([buildPage(samples="")]))
        self.assertEqual(counts["scraped"], 1)
        self.assertEqual(client.writesTo("sample_tests", "upsert"), [])
        self.assertEqual(len(client.writesTo("problem_specifications", "upsert")), 1)
        self.assertEqual(client.statusUpdates()[0][1]["stage_status"], "SCRAPED_WAITING_FOR_CONTEST")

    def test_marks_scraped_and_clears_any_previous_error(self):
        client = FakeClient(problemRows(1))
        runBatch(client, scripted([buildPage()]))
        problemId, payload = client.statusUpdates()[0]
        self.assertEqual(problemId, "1800_A")
        self.assertEqual(payload["stage_status"], "SCRAPED_WAITING_FOR_CONTEST")
        self.assertIsNone(payload["last_error"])

    def test_fetches_by_contest_id_and_index(self):
        fetchPage = scripted([buildPage()])
        runBatch(FakeClient(problemRows(1)), fetchPage)
        self.assertEqual(fetchPage.calls, [(1800, "A")])


class FailureTests(unittest.TestCase):
    def test_transient_failure_counts_an_attempt_and_leaves_the_problem_discoverable(self):
        client = FakeClient(problemRows(1, scrapeAttempts=1))
        counts, _ = runBatch(client, scripted([TransientScrapeError("HTTP 429 while fetching")]))

        _, payload = client.statusUpdates()[0]
        self.assertEqual(payload["scrape_attempts"], 2)
        self.assertEqual(payload["last_error"], "HTTP 429 while fetching")
        self.assertNotIn("stage_status", payload)
        self.assertEqual(counts, {"scraped": 0, "failed": 0, "retry_later": 1})

    def test_transient_failure_on_the_last_allowed_attempt_marks_failed(self):
        client = FakeClient(problemRows(1, scrapeAttempts=MAX_SCRAPE_ATTEMPTS - 1))
        counts, _ = runBatch(client, scripted([TransientScrapeError("HTTP 503")]))

        _, payload = client.statusUpdates()[0]
        self.assertEqual(payload["stage_status"], "FAILED")
        self.assertEqual(counts, {"scraped": 0, "failed": 1, "retry_later": 0})

    def test_validation_failure_marks_failed_with_the_reason(self):
        client = FakeClient(problemRows(1))
        counts, _ = runBatch(client, scripted([buildPage(outputSection="")]))

        _, payload = client.statusUpdates()[0]
        self.assertEqual(payload["stage_status"], "FAILED")
        self.assertIn("Neither an Output nor an Interaction", payload["last_error"])
        self.assertEqual(counts["failed"], 1)
        self.assertEqual(client.writesTo("problem_specifications", "upsert"), [])

    def test_page_not_found_marks_failed(self):
        client = FakeClient(problemRows(1))
        runBatch(client, scripted([ScrapingValidationError("Problem page not found (HTTP 404)")]))
        _, payload = client.statusUpdates()[0]
        self.assertEqual(payload["stage_status"], "FAILED")
        self.assertIn("404", payload["last_error"])

    def test_unexpected_error_marks_failed_and_the_run_continues_with_the_next_problem(self):
        client = FakeClient(problemRows(2), failingUpsertTables=["problem_specifications"])
        counts, _ = runBatch(client, scripted([buildPage(), buildPage()]))

        updates = client.statusUpdates()
        self.assertEqual([problemId for problemId, _ in updates], ["1800_A", "1800_B"])
        for _, payload in updates:
            self.assertEqual(payload["stage_status"], "FAILED")
            self.assertIn("boom on problem_specifications", payload["last_error"])
        self.assertEqual(counts["failed"], 2)


class CircuitBreakerTests(unittest.TestCase):
    def test_aborts_after_too_many_consecutive_transient_failures(self):
        problems = problemRows(8)
        fetchPage = scripted([TransientScrapeError("HTTP 403")] * 8)
        client = FakeClient(problems)
        counts, _ = runBatch(client, fetchPage)

        self.assertEqual(len(fetchPage.calls), MAX_CONSECUTIVE_TRANSIENT_FAILURES)
        self.assertEqual(len(client.statusUpdates()), MAX_CONSECUTIVE_TRANSIENT_FAILURES)
        self.assertEqual(counts["retry_later"], MAX_CONSECUTIVE_TRANSIENT_FAILURES)

    def test_a_success_resets_the_consecutive_failure_count(self):
        blocked = TransientScrapeError("HTTP 429")
        fetchPage = scripted([blocked] * 4 + [buildPage()] + [blocked] * 4)
        counts, _ = runBatch(FakeClient(problemRows(9)), fetchPage)

        self.assertEqual(len(fetchPage.calls), 9)
        self.assertEqual(counts, {"scraped": 1, "failed": 0, "retry_later": 8})

    def test_a_validation_failure_also_resets_the_count_because_the_site_answered(self):
        blocked = TransientScrapeError("HTTP 429")
        fetchPage = scripted([blocked] * 4 + [buildPage(outputSection="")] + [blocked] * 4)
        runBatch(FakeClient(problemRows(9)), fetchPage)
        self.assertEqual(len(fetchPage.calls), 9)


class PacingTests(unittest.TestCase):
    def test_waits_between_requests_but_not_before_the_first(self):
        _, sleeps = runBatch(FakeClient(problemRows(3)), scripted([buildPage()] * 3), delaySeconds=2.0)
        self.assertEqual(sleeps, [2.0, 2.0])

    def test_zero_delay_never_sleeps(self):
        _, sleeps = runBatch(FakeClient(problemRows(3)), scripted([buildPage()] * 3), delaySeconds=0)
        self.assertEqual(sleeps, [])


if __name__ == "__main__":
    unittest.main()
