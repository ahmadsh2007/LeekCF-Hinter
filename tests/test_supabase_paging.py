import unittest

from src.utils.supabasePaging import PAGE_SIZE, fetchAllRows
from tests.fakeSupabase import FakeSupabase


class FetchAllRowsFilterTests(unittest.TestCase):
    def test_equals_filters_every_page(self):
        rows = [{"id": f"{i:05d}", "stage_status": "WAITING" if i % 2 == 0 else "OTHER"} for i in range(4000)]
        client = FakeSupabase({"problems": rows})

        fetched = fetchAllRows(client, "problems", "id", "id", equals={"stage_status": "WAITING"})

        self.assertEqual(len(fetched), 2000)
        self.assertTrue(all(row["id"] for row in fetched))
        for call in client.selects("problems"):
            self.assertEqual(call.eqFilters, [("stage_status", "WAITING")])

    def test_several_order_columns_page_a_table_whose_key_has_two_parts_without_skipping_rows(self):
        rows = [{"problem_id": f"p{i // 3:04d}", "test_order": i % 3, "v": i} for i in range(2500)]
        client = FakeSupabase({"sample_tests": rows})
        fetched = fetchAllRows(client, "sample_tests", "*", ["problem_id", "test_order"])
        self.assertEqual(len(fetched), 2500)
        self.assertEqual(len({(r["problem_id"], r["test_order"]) for r in fetched}), 2500)
        self.assertEqual(client.selects("sample_tests")[0].orderColumns, ["problem_id", "test_order"])

    def test_page_size_matches_the_supabase_cap(self):
        self.assertEqual(PAGE_SIZE, 1000)


if __name__ == "__main__":
    unittest.main()
