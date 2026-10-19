import argparse
import gzip
import json
import os
import sys
from src.workers.backup.exportDatabase import MANIFEST, BackupError, fileName
from src.workers.backup.tables import TABLES, BackupTable

DEFAULT_BATCH_SIZE = 100  # rows carry whole statements, so keep write requests small

def loadBackup(directory: str) -> dict[str, list[dict]]:
    """Reads and checks a whole backup before anything is written: a damaged backup must not half-restore."""
    manifestPath = os.path.join(directory, MANIFEST)
    if not os.path.isfile(manifestPath):
        raise BackupError(f"{directory} is not a backup: there is no {MANIFEST}.")
    with open(manifestPath, encoding="utf-8") as handle:
        manifest = json.load(handle)

    data: dict[str, list[dict]] = {}
    for table in TABLES:
        path = os.path.join(directory, fileName(table))
        if not os.path.isfile(path) or table.name not in manifest["tables"]:
            raise BackupError(f"The backup is missing the table {table.name}.")
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        expected = manifest["tables"][table.name]["rows"]
        if len(rows) != expected:
            raise BackupError(f"{table.name}: the manifest says {expected} rows but the file has {len(rows)}; the backup is damaged.")
        data[table.name] = rows
    return data

def batchesOf(rows: list[dict], size: int):
    for start in range(0, len(rows), size):
        yield rows[start:start + size]

def writeTable(client, table: BackupTable, rows: list[dict], batchSize: int) -> None:
    for batch in batchesOf(rows, batchSize):
        client.table(table.name).upsert(batch, on_conflict=",".join(table.keyColumns)).execute()

def countRows(client, table: BackupTable) -> int:
    return client.table(table.name).select(table.keyColumns[0], count="exact").range(0, 0).execute().count

def restoreDatabase(client, directory: str, apply: bool = False, batchSize: int = DEFAULT_BATCH_SIZE, verify: bool = False) -> dict:
    """
    Puts a backup into a project that already has the tables (migrations 000-004). Rows are upserted on their natural
    keys, so running it again changes nothing, and nothing is written unless `apply` is true.
    """
    data = loadBackup(directory)
    result: dict = {name: len(rows) for name, rows in data.items()}

    if apply:
        for table in TABLES:
            rows = data[table.name]
            if table.name == "problems":
                # A duplicate points at its canonical problem, which must already be stored.
                writeTable(client, table, [r for r in rows if r.get("canonical_problem_id") is None], batchSize)
                writeTable(client, table, [r for r in rows if r.get("canonical_problem_id") is not None], batchSize)
            else:
                writeTable(client, table, rows, batchSize)
            print(f"  {table.name}: {len(rows):,} rows written")

    if verify:
        mismatches = []
        for table in TABLES:
            have = countRows(client, table)
            if have != result[table.name]:
                mismatches.append(f"{table.name}: backup has {result[table.name]} rows, the project has {have}")
        result["_mismatches"] = mismatches
    return result

def main():
    parser = argparse.ArgumentParser(description="Restore a backup made by exportDatabase into the project in ENV_FILE.")
    parser.add_argument("--from", dest="source", required=True, help="The backup folder.")
    parser.add_argument("--apply", action="store_true", help="Really write. Without it, only the backup is checked and counted.")
    parser.add_argument("--verify", action="store_true", help="Afterwards compare the row counts of the project with the backup.")
    args = parser.parse_args()

    # Imported here so the module can be imported (e.g. by tests) without database credentials.
    from src.core.database.dbClient import supabase
    try:
        result = restoreDatabase(supabase, args.source, apply=args.apply, verify=args.verify)
    except BackupError as e:
        print(f"Stopping: {e}")
        sys.exit(1)
    print(("Restored: " if args.apply else "Checked (nothing written; add --apply to restore): ")
          + ", ".join(f"{name} {count:,}" for name, count in result.items() if not name.startswith("_")))
    for problem in result.get("_mismatches", []):
        print(f"MISMATCH {problem}")
    if args.verify and not result.get("_mismatches"):
        print("Verified: the row counts match the backup.")

if __name__ == "__main__":
    main()
