PAGE_SIZE = 1000  # Supabase returns at most 1000 rows per request

def fetchAllRows(client, table: str, columns: str, orderColumn: str | list[str], equals: dict | None = None,
                 greaterThan: dict | None = None) -> list[dict]:
    """
    Reads a whole table (optionally only rows where every column in `equals` has that value and every column in
    `greaterThan` is above its value), page by page.
    Pages are only reliable when the order is unique: give several columns when the key has several parts.
    """
    orderColumns = [orderColumn] if isinstance(orderColumn, str) else list(orderColumn)
    rows: list[dict] = []
    page = 0
    while True:
        start = page * PAGE_SIZE
        query = client.table(table).select(columns)
        for column, value in (equals or {}).items():
            query = query.eq(column, value)
        for column, value in (greaterThan or {}).items():
            query = query.gt(column, value)
        for column in orderColumns:
            query = query.order(column)
        batch = query.range(start, start + PAGE_SIZE - 1).execute().data
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
        page += 1
