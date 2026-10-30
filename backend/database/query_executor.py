"""Runs SQL on the shared read-only connection with row limits and a timeout."""

import threading
import time
from typing import Any

from backend.config import MAX_QUERY_ROWS, QUERY_TIMEOUT_SECONDS
from backend.database.connection import connection

# A single sqlite3 connection must not be used by several threads at the same time.
_connection_lock = threading.Lock()


def run_query(sql: str) -> dict[str, Any]:
    """Execute a read-only SELECT/WITH query and return columns, rows, and timing."""
    cleaned_sql = sql.strip().rstrip(";")
    if not cleaned_sql:
        raise ValueError("SQL query cannot be empty.")
    if cleaned_sql.split()[0].upper() not in {"SELECT", "WITH"}:
        raise PermissionError("Only read-only SELECT or WITH queries are permitted.")

    start_time = time.perf_counter()
    deadline = start_time + QUERY_TIMEOUT_SECONDS

    with _connection_lock:
        # Returning a non-zero value from the progress handler aborts a long-running query.
        connection.set_progress_handler(lambda: int(time.perf_counter() > deadline), 10000)
        try:
            cursor = connection.execute(cleaned_sql)
            rows = cursor.fetchmany(MAX_QUERY_ROWS)
            columns = [col[0] for col in cursor.description] if cursor.description else []
        finally:
            connection.set_progress_handler(None, 0)

    results = [dict(row) for row in rows]
    return {
        "columns": columns,
        "results": results,
        "row_count": len(results),
        "execution_ms": round((time.perf_counter() - start_time) * 1000, 2),
    }


def explain_query(sql: str) -> str | None:
    """Return SQLite's error message if the query cannot be planned, otherwise None."""
    with _connection_lock:
        try:
            connection.execute(f"EXPLAIN QUERY PLAN {sql};")
            return None
        except Exception as exc:
            return str(exc)


def get_table_row_counts() -> dict[str, int]:
    """Return row counts for every user table in the database."""
    with _connection_lock:
        tables = [
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
            )
        ]
        return {t: connection.execute(f"SELECT COUNT(*) FROM {t};").fetchone()[0] for t in tables}

