import csv
import os
import tempfile
import unittest

from src.utils.statementHash import computeStatementHash
from src.workers.dedup.dedupPlanner import DedupProblem
from src.workers.dedup.dedupProblems import (
    LINK_CHUNK_SIZE,
    SAVE_BATCH_SIZE,
    applyLinks,
    buildDedupProblems,
    fetchAllRows,
    loadStatementHashes,
    run,
    saveHashes,
    writeReviewReport,
)
from tests.fakeSupabase import FakeSupabase


def specsRow(problemId, statementHash=None, statement="stmt") -> dict:
    return {
        "problem_id": problemId,
        "time_limit_ms": 1000,
        "memory_limit_mb": 256,
        "statement_text": statement,
        "input_specification": "in",
        "output_specification": "out",
        "interaction_specification": None,
        "notes": "keep me",
        "statement_hash": statementHash,
    }


class FetchAllRowsTests(unittest.TestCase):
    def test_pages_through_the_table_in_order(self):
        client = FakeSupabase({"problems": [{"id": f"{i:05d}"} for i in range(2500)]})
        rows = fetchAllRows(client, "problems", "id", "id")

        self.assertEqual(len(rows), 2500)
        self.assertEqual(rows[0]["id"], "00000")
        self.assertEqual(rows[-1]["id"], "02499")
        self.assertEqual([call.rangeBounds for call in client.selects("problems")], [(0, 999), (1000, 1999), (2000, 2999)])
        self.assertTrue(all(call.orderColumn == "id" for call in client.selects("problems")))

    def test_an_exact_multiple_of_the_page_size_needs_one_more_request_to_notice_the_end(self):
        client = FakeSupabase({"problems": [{"id": f"{i:05d}"} for i in range(1000)]})
        self.assertEqual(len(fetchAllRows(client, "problems", "id", "id")), 1000)
        self.assertEqual(len(client.selects("problems")), 2)

    def test_empty_table(self):
        self.assertEqual(fetchAllRows(FakeSupabase(), "problems", "id", "id"), [])


class BuildDedupProblemsTests(unittest.TestCase):
    def test_joins_contest_start_time_and_statement_hash(self):
        problemRows = [
            {"id": "1000_A", "name": "Foo", "contest_id": 1000, "stage_status": "HINTS_GENERATED", "canonical_problem_id": None},
            {"id": "1001_C", "name": "Foo", "contest_id": 1001, "stage_status": "DUPLICATE", "canonical_problem_id": "1000_A"},
            {"id": "1002_B", "name": "Bar", "contest_id": 1002, "stage_status": "DISCOVERED", "canonical_problem_id": None},
        ]
        contestRows = [
            {"id": 1000, "start_time": "2024-01-01T12:00:00+00:00"},
            {"id": 1001, "start_time": "2024-01-01T12:00:00+00:00"},
            {"id": 1002, "start_time": "2024-02-01T12:00:00+00:00"},
        ]
        problems = buildDedupProblems(problemRows, contestRows, {"1000_A": "h1", "1001_C": "h1"})

        self.assertEqual(problems[0], DedupProblem(
            id="1000_A", name="Foo", contestId=1000, stageStatus="HINTS_GENERATED",
            canonicalProblemId=None, startTime="2024-01-01T12:00:00+00:00", statementHash="h1"))
        self.assertEqual(problems[1].canonicalProblemId, "1000_A")
        self.assertIsNone(problems[2].statementHash)


class LoadStatementHashesTests(unittest.TestCase):
    def test_keeps_stored_hashes_and_computes_missing_ones_without_writing(self):
        client = FakeSupabase({"problem_specifications": [
            specsRow("1000_A", statementHash="stored"),
            specsRow("1000_B", statementHash=None, statement="needs a hash"),
        ]})
        hashes, backfillRows = loadStatementHashes(client)

        expected = computeStatementHash({
            "time_limit_ms": 1000, "memory_limit_mb": 256, "statement_text": "needs a hash",
            "input_specification": "in", "output_specification": "out", "interaction_specification": None,
        })
        self.assertEqual(hashes, {"1000_A": "stored", "1000_B": expected})
        self.assertEqual([row["problem_id"] for row in backfillRows], ["1000_B"])
        self.assertEqual(backfillRows[0]["statement_hash"], expected)
        self.assertEqual(backfillRows[0]["notes"], "keep me")
        self.assertEqual([call for call in client.calls if call.operation != "select"], [])

    def test_nothing_to_backfill(self):
        client = FakeSupabase({"problem_specifications": [specsRow("1000_A", statementHash="stored")]})
        hashes, backfillRows = loadStatementHashes(client)
        self.assertEqual(hashes, {"1000_A": "stored"})
        self.assertEqual(backfillRows, [])


class SaveHashesTests(unittest.TestCase):
    def test_upserts_full_rows_in_batches(self):
        rows = [specsRow(f"{i}_A", statementHash="h") for i in range(SAVE_BATCH_SIZE * 2 + 50)]
        client = FakeSupabase()
        saveHashes(client, rows)

        upserts = client.writes("problem_specifications", "upsert")
        self.assertEqual([len(call.payload) for call in upserts], [SAVE_BATCH_SIZE, SAVE_BATCH_SIZE, 50])


class ApplyLinksTests(unittest.TestCase):
    def test_marks_duplicates_per_canonical_with_one_update_each(self):
        client = FakeSupabase()
        applyLinks(client, [("1001_C", "1000_A"), ("1002_B", "1000_A"), ("2001_C", "2000_A")])

        updates = client.writes("problems", "update")
        self.assertEqual(len(updates), 2)
        first = updates[0]
        self.assertEqual(first.payload, {"stage_status": "DUPLICATE", "canonical_problem_id": "1000_A", "updated_at": "now()"})
        self.assertEqual(first.inFilters, [("id", ["1001_C", "1002_B"])])
        self.assertEqual(updates[1].payload["canonical_problem_id"], "2000_A")
        self.assertEqual(updates[1].inFilters, [("id", ["2001_C"])])

    def test_long_id_lists_are_chunked(self):
        links = [(f"{i}_C", "1000_A") for i in range(LINK_CHUNK_SIZE * 2 + 1)]
        client = FakeSupabase()
        applyLinks(client, links)
        self.assertEqual([len(call.inFilters[0][1]) for call in client.writes("problems", "update")],
                         [LINK_CHUNK_SIZE, LINK_CHUNK_SIZE, 1])

    def test_no_links_makes_no_requests(self):
        client = FakeSupabase()
        applyLinks(client, [])
        self.assertEqual(client.calls, [])


class WriteReviewReportTests(unittest.TestCase):
    def test_writes_one_row_per_member_numbered_by_group(self):
        reviews = [
            [DedupProblem("1000_A", "Foo", 1000, "SCRAPED_WAITING_FOR_CONTEST", None, "2024-01-01T12:00:00+00:00", "aaaa"),
             DedupProblem("1001_C", "Foo", 1001, "SCRAPED_WAITING_FOR_CONTEST", None, "2024-01-01T12:00:00+00:00", "bbbb")],
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "review.csv")
            writeReviewReport(path, reviews)
            with open(path, newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], {
            "group": "1", "problem_id": "1000_A", "name": "Foo", "contest_id": "1000",
            "start_time": "2024-01-01T12:00:00+00:00", "statement_hash": "aaaa"})
        self.assertEqual(rows[1]["problem_id"], "1001_C")


class RunTests(unittest.TestCase):
    START = "2024-01-01T12:00:00+00:00"

    def makeClient(self) -> FakeSupabase:
        problem = {"name": "Foo", "stage_status": "SCRAPED_WAITING_FOR_CONTEST", "canonical_problem_id": None}
        return FakeSupabase({
            "problems": [
                {"id": "1000_A", "contest_id": 1000, **problem},
                {"id": "1001_C", "contest_id": 1001, **problem},
            ],
            "contests": [
                {"id": 1000, "start_time": self.START},
                {"id": 1001, "start_time": self.START},
            ],
            "problem_specifications": [specsRow("1000_A"), specsRow("1001_C")],
        })

    def test_dry_run_plans_the_link_but_writes_nothing(self):
        client = self.makeClient()
        plan = run(client, apply=False, reportPath=None)

        self.assertEqual(plan.links, [("1001_C", "1000_A")])
        self.assertEqual([call for call in client.calls if call.operation != "select"], [])

    def test_apply_saves_the_hashes_first_and_then_links_the_duplicates(self):
        client = self.makeClient()
        run(client, apply=True, reportPath=None)

        writes = [(call.tableName, call.operation) for call in client.calls if call.operation != "select"]
        self.assertEqual(writes, [("problem_specifications", "upsert"), ("problems", "update")])
        savedHashes = [row["statement_hash"] for row in client.writes("problem_specifications", "upsert")[0].payload]
        self.assertEqual(len(savedHashes), 2)
        self.assertEqual(len(set(savedHashes)), 1)

    def test_a_review_report_is_written_even_on_a_dry_run(self):
        client = self.makeClient()
        client.tables["problem_specifications"][1] = specsRow("1001_C", statement="a different statement")
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "review.csv")
            plan = run(client, apply=False, reportPath=path)
            with open(path, newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(plan.links, [])
        self.assertEqual([row["problem_id"] for row in rows], ["1000_A", "1001_C"])


if __name__ == "__main__":
    unittest.main()
