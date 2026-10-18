PAGE_SIZE = 1000  # Supabase returns at most 1000 rows per request

def fetchAllRows(client, table: str, columns: str, orderColumn: str, equals: dict | None = None) -> list[dict]:
    """Reads a whole table (optionally only rows where every column in `equals` has that value), page by page."""
    rows: list[dict] = []
    page = 0
    while True:
        start = page * PAGE_SIZE
        query = client.table(table).select(columns)
        for column, value in (equals or {}).items():
            query = query.eq(column, value)
        batch = query.order(orderColumn).range(start, start + PAGE_SIZE - 1).execute().data
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
        page += 1
