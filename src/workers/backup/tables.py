from dataclasses import dataclass

@dataclass(frozen=True)
class BackupTable:
    name: str
    orderColumns: tuple[str, ...]   # a unique order, so that paging never skips or repeats a row
    keyColumns: tuple[str, ...]     # the natural key a restore upserts on
    dropColumns: tuple[str, ...] = ()  # auto-numbered ids: the database refuses explicit values and the key above identifies rows
    addedLater: bool = False           # a backup made before this table existed simply does not have it

# In the order a restore must write them (a row may point at rows of the tables before it).
TABLES = (
    BackupTable("contests", ("id",), ("id",)),
    BackupTable("problems", ("id",), ("id",)),
    BackupTable("problem_specifications", ("problem_id",), ("problem_id",)),
    BackupTable("sample_tests", ("problem_id", "test_order"), ("problem_id", "test_order")),
    BackupTable("tutorials", ("id",), ("problem_id",), dropColumns=("id",)),
    BackupTable("hints", ("id",), ("problem_id", "hint_level"), dropColumns=("id",)),
    # The request statistics of the public API (migration 005): they cannot be regenerated, unlike everything above.
    BackupTable("api_usage_daily", ("day", "client", "route", "status"), ("day", "client", "route", "status"), addedLater=True),
)
