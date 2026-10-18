import importlib
import sys
import types
import unittest
from unittest.mock import patch

from tests.fakeSupabase import FakeSupabase

MODULE_NAME = "src.core.database.admin.ProblemWithTargetedTagRemover"


def problemRow(problemId, tags, canonical=None) -> dict:
    return {"id": problemId, "tags": tags, "canonical_problem_id": canonical}


class TagRemoverTests(unittest.TestCase):
    def runRemover(self, fake: FakeSupabase, tag: str = ""):
        """Runs the real admin function with the database client, the safety prompts and input() replaced."""
        fakeDbClient = types.ModuleType("src.core.database.dbClient")
        fakeDbClient.supabase = fake
        sys.modules.pop(MODULE_NAME, None)
        with patch.dict(sys.modules, {"src.core.database.dbClient": fakeDbClient}):
            module = importlib.import_module(MODULE_NAME)
            with patch.object(module, "verifyAction", return_value=True), patch("builtins.input", return_value=tag):
                module.changeDatabaseValueViaBulkChange()
        sys.modules.pop(MODULE_NAME, None)

    def test_deletes_only_from_problems_and_removes_duplicates_before_their_canonical(self):
        fake = FakeSupabase({"problems": [
            problemRow("1000_A", ["*special"]),
            problemRow("1001_C", ["*special"], canonical="1000_A"),
            problemRow("1002_B", ["dp"]),
        ]})
        self.runRemover(fake)

        deletes = [call for call in fake.calls if call.operation == "delete"]
        self.assertEqual([call.tableName for call in deletes], ["problems"])
        self.assertEqual(deletes[0].inFilters, [("id", ["1001_C", "1000_A"])])
        self.assertEqual([row["id"] for row in fake.tables["problems"]], ["1002_B"])

    def test_deletes_in_chunks_of_100(self):
        fake = FakeSupabase({"problems": [problemRow(f"{i}_A", ["*special"]) for i in range(250)]})
        self.runRemover(fake)

        deletes = [call for call in fake.calls if call.operation == "delete"]
        self.assertEqual([len(call.inFilters[0][1]) for call in deletes], [100, 100, 50])
        self.assertEqual(fake.tables["problems"], [])

    def test_a_custom_tag_is_honoured(self):
        fake = FakeSupabase({"problems": [problemRow("1000_A", ["*special"]), problemRow("1001_C", ["geometry"])]})
        self.runRemover(fake, tag="geometry")
        self.assertEqual([row["id"] for row in fake.tables["problems"]], ["1000_A"])

    def test_nothing_matching_changes_nothing(self):
        fake = FakeSupabase({"problems": [problemRow("1000_A", ["dp"])]})
        self.runRemover(fake)
        self.assertEqual([call for call in fake.calls if call.operation == "delete"], [])


if __name__ == "__main__":
    unittest.main()
