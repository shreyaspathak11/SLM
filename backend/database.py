"""Read-only SQLite database connector, schema extractor, and safe query executor."""

import os
from pathlib import Path
import sqlite3
import time
from typing import Any

from dotenv import load_dotenv

load_dotenv()

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "analytics.db"
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(DEFAULT_DB_PATH))).resolve()
MAX_ROWS = 5000


def get_readonly_connection(db_path: Path = DATABASE_PATH) -> sqlite3.Connection:
    """Open a strict read-only SQLite connection using URI mode."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database file not found at: {db_path}")

    uri = f"{db_path.as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def get_database_schema(db_path: Path = DATABASE_PATH) -> str:
    """Dynamically extract all CREATE TABLE DDL statements from sqlite_master."""
    with get_readonly_connection(db_path) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL
            ORDER BY name;
            """
        )
        statements = [
            " ".join(row["sql"].split()).rstrip(";") + ";"
            for row in cursor.fetchall()
        ]
    return "\n".join(statements)


def get_table_row_counts(db_path: Path = DATABASE_PATH) -> dict[str, int]:
    """Return row counts for every user table in the database."""
    counts: dict[str, int] = {}
    with get_readonly_connection(db_path) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name;
            """
        )
        tables = [row["name"] for row in cursor.fetchall()]
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) AS cnt FROM {table};")
            counts[table] = cursor.fetchone()["cnt"]
    return counts


def execute_readonly_query(
    sql_query: str,
    db_path: Path = DATABASE_PATH,
) -> dict[str, Any]:
    """Execute a validated read-only SQL query with timeout and row limits."""
    cleaned_sql = sql_query.strip().rstrip(";")
    if not cleaned_sql:
        raise ValueError("SQL query cannot be empty.")

    first_keyword = cleaned_sql.split()[0].upper()
    if first_keyword not in {"SELECT", "WITH"}:
        raise PermissionError("Only read-only SELECT or WITH queries are permitted.")

    start_time = time.perf_counter()
    deadline = start_time + 5.0

    def timeout_handler() -> int:
        return 1 if time.perf_counter() > deadline else 0

    with get_readonly_connection(db_path) as connection:
        connection.set_progress_handler(timeout_handler, 10000)
        cursor = connection.cursor()
        cursor.execute(cleaned_sql)
        rows = cursor.fetchmany(MAX_ROWS)
        columns = [col[0] for col in cursor.description] if cursor.description else []
        results = [dict(row) for row in rows]
    execution_ms = round((time.perf_counter() - start_time) * 1000, 2)

    return {
        "columns": columns,
        "results": results,
        "row_count": len(results),
        "execution_ms": execution_ms,
    }
