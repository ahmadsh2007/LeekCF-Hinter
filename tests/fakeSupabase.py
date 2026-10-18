"""An in-memory stand-in for the supabase-py query builder, just rich enough for the dedup worker's tests."""
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
        self.orderColumn = None
        self.rangeBounds = None

    def select(self, columns="*"):
        self.columns = columns
        return self

    def eq(self, column, value):
        self.eqFilters.append((column, value))
        return self

    def in_(self, column, values):
        self.inFilters.append((column, list(values)))
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

    def upsert(self, payload):
        self.operation = "upsert"
        self.payload = payload
        return self

    def execute(self):
        self.client.calls.append(self)
        if self.operation != "select":
            return SimpleNamespace(data=[])

        rows = [dict(row) for row in self.client.tables.get(self.tableName, [])]
        for column, value in self.eqFilters:
            rows = [row for row in rows if row.get(column) == value]
        for column, values in self.inFilters:
            rows = [row for row in rows if row.get(column) in values]
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
