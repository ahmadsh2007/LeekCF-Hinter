import argparse
import gzip
import json
import os
import shutil
import time
from datetime import datetime, timezone
from src.utils.supabasePaging import fetchAllRows
from src.workers.backup.tables import TABLES, BackupTable

MANIFEST = "manifest.json"
FORMAT_VERSION = 1

class BackupError(Exception):
    pass

def fileName(table: BackupTable) -> str:
    return f"{table.name}.ndjson.gz"

def readTable(client, table: BackupTable) -> list[dict]:
    rows = fetchAllRows(client, table.name, "*", list(table.orderColumns))
    unique: dict[tuple, dict] = {}
    for row in rows:  # a row that moved between pages while the pipeline was writing must not be saved twice
        unique[tuple(row[column] for column in table.keyColumns)] = {k: v for k, v in row.items() if k not in table.dropColumns}
    return list(unique.values())

def exportDatabase(client, outDir: str, now: datetime | None = None) -> dict:
    """
    Writes every table to <outDir>/<table>.ndjson.gz (one JSON row per line) and a manifest with the row counts.
    The folder appears only when the whole export succeeded, and an existing folder is never touched.
    """
    now = now or datetime.now(timezone.utc)
    if os.path.exists(outDir):
        raise BackupError(f"{outDir} already exists; choose a new folder (backups are never overwritten).")

    partial = outDir + ".partial"
    shutil.rmtree(partial, ignore_errors=True)
    os.makedirs(partial)
    try:
        manifest = {"format": FORMAT_VERSION, "exported_at": now.isoformat(), "tables": {}}
        for table in TABLES:
            rows = readTable(client, table)
            with gzip.open(os.path.join(partial, fileName(table)), "wt", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            manifest["tables"][table.name] = {"rows": len(rows), "file": fileName(table), "columns": sorted(rows[0]) if rows else []}
            print(f"  {table.name}: {len(rows):,} rows")
        with open(os.path.join(partial, MANIFEST), "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2)
        os.rename(partial, outDir)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return manifest

def main():
    parser = argparse.ArgumentParser(description="Save every table of the project to files on this computer.")
    parser.add_argument("--out", default=os.path.expanduser(f"~/leekcf-env/backups/{time.strftime('%Y-%m-%d_%H%M')}"),
                        help="A new folder to write into (default: ~/leekcf-env/backups/<date_time>).")
    args = parser.parse_args()

    # Imported here so the module can be imported (e.g. by tests) without database credentials.
    from src.core.database.dbClient import supabase
    print(f"Exporting to {args.out} ...")
    manifest = exportDatabase(supabase, args.out)
    print(f"Done: {sum(info['rows'] for info in manifest['tables'].values()):,} rows in {len(manifest['tables'])} tables.")
    print("Copy this folder somewhere that is not this computer (an external drive or a cloud drive).")

if __name__ == "__main__":
    main()
