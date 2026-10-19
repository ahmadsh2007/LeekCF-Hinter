import gzip
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from src.workers.backup.exportDatabase import exportDatabase
from src.workers.backup.restoreDatabase import BackupError, restoreDatabase
from src.workers.backup.tables import TABLES
from tests.fakeSupabase import FakeSupabase

NOW = datetime(2026, 10, 19, 21, 30, tzinfo=timezone.utc)

def sampleTables():
    return {
        "contests": [{"id": 1, "name": "Round 1", "type": "CF", "phase": "FINISHED", "start_time": "2024-01-01T12:00:00+00:00", "duration_seconds": 7200, "last_check_at": "2026-10-19T00:00:00+00:00"}],
        "problems": [
            {"id": "1_B", "contest_id": 1, "index": "B", "name": "Twin", "rating": 1200, "tags": ["dp"], "stage_status": "DUPLICATE", "canonical_problem_id": "1_A", "created_at": "x", "updated_at": "x"},
            {"id": "1_A", "contest_id": 1, "index": "A", "name": "Twin", "rating": 1200, "tags": ["dp"], "stage_status": "HINTS_GENERATED", "canonical_problem_id": None, "created_at": "x", "updated_at": "x"},
        ],
        "problem_specifications": [{"problem_id": "1_A", "statement_text": "Naïve $$$a \\le b$$$\nline two — ünïcode", "time_limit_ms": 1000}],
        "sample_tests": [{"problem_id": "1_A", "test_order": 2, "input_text": "2", "output_text": ""}, {"problem_id": "1_A", "test_order": 1, "input_text": "1", "output_text": "1"}],
        "tutorials": [{"id": 11, "problem_id": "1_A", "contest_id": 1, "source_url": "u", "raw_content": "t", "author": None, "scraped_at": "x"}],
        "hints": [
            {"id": 21, "problem_id": "1_A", "hint_level": 1, "content": "h1", "llm_model_used": "m", "prompt_version": "v2", "grounded_in_tutorial": True, "created_at": "x"},
            {"id": 22, "problem_id": "1_A", "hint_level": 2, "content": "h2", "llm_model_used": "m", "prompt_version": "v2", "grounded_in_tutorial": True, "created_at": "x"},
        ],
    }

def readBack(directory, table):
    with gzip.open(os.path.join(directory, f"{table}.ndjson.gz"), "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


class ExportTests(unittest.TestCase):
    def export(self, tables=None):
        self.directory = tempfile.mkdtemp()
        self.out = os.path.join(self.directory, "backup")
        self.client = FakeSupabase(tables or sampleTables())
        return exportDatabase(self.client, self.out, now=NOW)

    def test_one_file_per_table_and_a_manifest_with_the_counts(self):
        manifest = self.export()
        self.assertEqual(sorted(os.listdir(self.out)), sorted([f"{t.name}.ndjson.gz" for t in TABLES] + ["manifest.json"]))
        self.assertEqual({name: info["rows"] for name, info in manifest["tables"].items()},
                         {"contests": 1, "problems": 2, "problem_specifications": 1, "sample_tests": 2, "tutorials": 1, "hints": 2})
        self.assertEqual(manifest["exported_at"], NOW.isoformat())
        self.assertEqual(json.load(open(os.path.join(self.out, "manifest.json"))), manifest)

    def test_text_survives_the_round_trip_exactly(self):
        self.export()
        spec = readBack(self.out, "problem_specifications")[0]
        self.assertEqual(spec["statement_text"], "Naïve $$$a \\le b$$$\nline two — ünïcode")

    def test_tables_with_auto_numbered_ids_do_not_export_the_id(self):
        self.export()
        self.assertNotIn("id", readBack(self.out, "hints")[0])
        self.assertNotIn("id", readBack(self.out, "tutorials")[0])
        self.assertIn("id", readBack(self.out, "problems")[0])

    def test_a_table_with_a_two_part_key_comes_back_complete_and_in_key_order(self):
        tables = sampleTables()
        tables["sample_tests"] = [{"problem_id": f"p{i // 3:04d}", "test_order": 3 - i % 3, "input_text": "i", "output_text": "o"} for i in range(2500)]
        manifest = self.export(tables)
        rows = readBack(self.out, "sample_tests")
        self.assertEqual((manifest["tables"]["sample_tests"]["rows"], len(rows)), (2500, 2500))
        self.assertEqual(len({(r["problem_id"], r["test_order"]) for r in rows}), 2500)

    def test_the_orders_are_unique_keys_of_each_table(self):
        # Written out on purpose: sample_tests has a two-part key, and ordering by one part lets pages skip or repeat rows.
        self.assertEqual({t.name: t.orderColumns for t in TABLES}, {
            "contests": ("id",), "problems": ("id",), "problem_specifications": ("problem_id",),
            "sample_tests": ("problem_id", "test_order"), "tutorials": ("id",), "hints": ("id",),
        })
        self.assertEqual({t.name: t.keyColumns for t in TABLES}, {
            "contests": ("id",), "problems": ("id",), "problem_specifications": ("problem_id",),
            "sample_tests": ("problem_id", "test_order"), "tutorials": ("problem_id",), "hints": ("problem_id", "hint_level"),
        })

    def test_every_table_is_read_in_a_unique_order_or_paging_could_skip_rows(self):
        self.export()
        for table in TABLES:
            asked = [call.orderColumns for call in self.client.selects(table.name)]
            self.assertTrue(asked and all(order == list(table.orderColumns) for order in asked), table.name)

    def test_a_row_seen_twice_while_paging_is_saved_once(self):
        tables = sampleTables()
        tables["problems"] = tables["problems"] + [dict(tables["problems"][1])]  # the pipeline moved a row between pages
        manifest = self.export(tables)
        self.assertEqual(manifest["tables"]["problems"]["rows"], 2)
        self.assertEqual(sorted(r["id"] for r in readBack(self.out, "problems")), ["1_A", "1_B"])

    def test_empty_tables_are_fine(self):
        manifest = self.export({t.name: [] for t in TABLES})
        self.assertTrue(all(info["rows"] == 0 for info in manifest["tables"].values()))

    def test_it_never_writes_into_an_existing_folder(self):
        self.export()
        with self.assertRaises(BackupError):
            exportDatabase(FakeSupabase(sampleTables()), self.out, now=NOW)

    def test_a_failed_export_leaves_no_half_backup_behind(self):
        directory = tempfile.mkdtemp()
        out = os.path.join(directory, "backup")
        class Broken(FakeSupabase):
            def table(self, name):
                if name == "hints":
                    raise RuntimeError("database vanished")
                return super().table(name)
        with self.assertRaises(RuntimeError):
            exportDatabase(Broken(sampleTables()), out, now=NOW)
        self.assertFalse(os.path.exists(out))
        self.assertFalse(os.path.exists(out + ".partial"))


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.out = os.path.join(self.directory, "backup")
        exportDatabase(FakeSupabase(sampleTables()), self.out, now=NOW)

    def upserts(self, target):
        return [call for call in target.calls if call.operation == "upsert"]

    def test_by_default_nothing_is_written(self):
        target = FakeSupabase({})
        result = restoreDatabase(target, self.out, apply=False)
        self.assertEqual(self.upserts(target), [])
        self.assertEqual(result["problems"], 2)

    def test_apply_writes_tables_in_dependency_order(self):
        target = FakeSupabase({})
        restoreDatabase(target, self.out, apply=True)
        order = []
        for call in self.upserts(target):
            if call.tableName not in order:
                order.append(call.tableName)
        self.assertEqual(order, ["contests", "problems", "problem_specifications", "sample_tests", "tutorials", "hints"])

    def test_a_problem_is_stored_before_the_duplicate_that_points_at_it(self):
        target = FakeSupabase({})
        restoreDatabase(target, self.out, apply=True)
        sent = [row["id"] for call in self.upserts(target) if call.tableName == "problems" for row in call.payload]
        self.assertEqual(sent, ["1_A", "1_B"])  # the canonical first, although the file lists the duplicate first
        batches = [[row["id"] for row in call.payload] for call in self.upserts(target) if call.tableName == "problems"]
        self.assertEqual(batches, [["1_A"], ["1_B"]])

    def test_rows_are_upserted_on_their_natural_keys_so_a_rerun_changes_nothing_new(self):
        target = FakeSupabase({})
        restoreDatabase(target, self.out, apply=True)
        keys = {call.tableName: call.onConflict for call in self.upserts(target)}
        self.assertEqual(keys, {
            "contests": "id", "problems": "id", "problem_specifications": "problem_id",
            "sample_tests": "problem_id,test_order", "tutorials": "problem_id", "hints": "problem_id,hint_level",
        })

    def test_requests_stay_small(self):
        tables = sampleTables()
        tables["sample_tests"] = [{"problem_id": f"p{i:05d}", "test_order": 1, "input_text": "i", "output_text": "o"} for i in range(250)]
        directory = os.path.join(tempfile.mkdtemp(), "b")
        exportDatabase(FakeSupabase(tables), directory, now=NOW)
        target = FakeSupabase({})
        restoreDatabase(target, directory, apply=True, batchSize=100)
        sizes = [len(call.payload) for call in self.upserts(target) if call.tableName == "sample_tests"]
        self.assertEqual(sizes, [100, 100, 50])

    def test_the_text_that_goes_back_is_the_text_that_was_saved(self):
        target = FakeSupabase({})
        restoreDatabase(target, self.out, apply=True)
        spec = next(call for call in self.upserts(target) if call.tableName == "problem_specifications").payload[0]
        self.assertEqual(spec["statement_text"], "Naïve $$$a \\le b$$$\nline two — ünïcode")

    def test_a_folder_that_is_not_a_backup_is_refused(self):
        with self.assertRaises(BackupError):
            restoreDatabase(FakeSupabase({}), self.directory, apply=True)

    def test_a_backup_with_a_missing_table_file_is_refused_before_anything_is_written(self):
        os.remove(os.path.join(self.out, "hints.ndjson.gz"))
        target = FakeSupabase({})
        with self.assertRaises(BackupError):
            restoreDatabase(target, self.out, apply=True)
        self.assertEqual(self.upserts(target), [])

    def test_a_truncated_file_is_refused_because_its_row_count_disagrees_with_the_manifest(self):
        with gzip.open(os.path.join(self.out, "problems.ndjson.gz"), "wt", encoding="utf-8") as handle:
            handle.write(json.dumps({"id": "1_A"}) + "\n")
        target = FakeSupabase({})
        with self.assertRaises(BackupError):
            restoreDatabase(target, self.out, apply=True)
        self.assertEqual(self.upserts(target), [])

    def test_verification_compares_the_target_counts_with_the_manifest(self):
        good = FakeSupabase(sampleTables())
        self.assertEqual(restoreDatabase(good, self.out, apply=False, verify=True)["_mismatches"], [])
        short = sampleTables()
        short["hints"] = short["hints"][:1]
        mismatches = restoreDatabase(FakeSupabase(short), self.out, apply=False, verify=True)["_mismatches"]
        self.assertEqual(mismatches, ["hints: backup has 2 rows, the project has 1"])


if __name__ == "__main__":
    unittest.main()
