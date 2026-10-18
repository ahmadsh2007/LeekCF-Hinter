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

    def test_page_size_matches_the_supabase_cap(self):
        self.assertEqual(PAGE_SIZE, 1000)


if __name__ == "__main__":
    unittest.main()
