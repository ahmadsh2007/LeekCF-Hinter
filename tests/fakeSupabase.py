"""An in-memory stand-in for the supabase-py query builder, just rich enough for the worker and admin tests."""
from types import SimpleNamespace


class FakeQuery:
    def __init__(self, client, tableName):
        self.client = client
        self.tableName = tableName
        self.operation = "select"
        self.payload = None
        self.columns = "*"
        self.eqFilters = []
        self.inFilters = []
        self.containsFilters = []
        self.gtFilters = []
        self.orderColumn = None
        self.rangeBounds = None
        self.onConflict = None

    def select(self, columns="*"):
        self.columns = columns
        return self

    def eq(self, column, value):
        self.eqFilters.append((column, value))
        return self

    def in_(self, column, values):
        self.inFilters.append((column, list(values)))
        return self

    def gt(self, column, value):
        self.gtFilters.append((column, value))
        return self

    def contains(self, column, values):
        self.containsFilters.append((column, list(values)))
        return self

    def order(self, column):
        self.orderColumn = column
        return self

    def range(self, start, end):
        self.rangeBounds = (start, end)
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self.operation = "upsert"
        self.payload = payload
        self.onConflict = on_conflict
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def matches(self, row) -> bool:
        return (
            all(row.get(column) == value for column, value in self.eqFilters)
            and all(row.get(column) in values for column, values in self.inFilters)
            and all(row.get(column) is not None and row.get(column) > value for column, value in self.gtFilters)
            and all(all(value in (row.get(column) or []) for value in values) for column, values in self.containsFilters)
        )

    def execute(self):
        self.client.calls.append(self)
        if self.operation in ("update", "upsert"):
            return SimpleNamespace(data=[])

        tableRows = self.client.tables.get(self.tableName, [])
        matched = [dict(row) for row in tableRows if self.matches(row)]

        if self.operation == "delete":
            self.client.tables[self.tableName] = [row for row in tableRows if not self.matches(row)]
            return SimpleNamespace(data=matched)

        rows = matched
        if self.orderColumn:
            rows.sort(key=lambda row: row[self.orderColumn])
        if self.rangeBounds:
            start, end = self.rangeBounds
            rows = rows[start:end + 1]
        if self.columns != "*":
            wanted = [column.strip() for column in self.columns.split(",")]
            rows = [{column: row[column] for column in wanted} for row in rows]
        return SimpleNamespace(data=rows)


class FakeSupabase:
    def __init__(self, tables=None):
        self.tables = tables or {}
        self.calls = []

    def table(self, tableName):
        return FakeQuery(self, tableName)

    def writes(self, tableName, operation):
        return [call for call in self.calls if call.tableName == tableName and call.operation == operation]

    def selects(self, tableName):
        return self.writes(tableName, "select")
