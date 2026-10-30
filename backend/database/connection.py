"""Singleton read-only SQLite connection shared across the backend."""

import sqlite3

from backend.config import DATABASE_PATH, QUERY_TIMEOUT_SECONDS
from backend.database.setup import ensure_database


def create_connection() -> sqlite3.Connection:
    """Ensure the database exists and open a strict read-only connection to it."""
    ensure_database(DATABASE_PATH)
    connection = sqlite3.connect(
        f"{DATABASE_PATH.as_uri()}?mode=ro",
        uri=True,
        timeout=QUERY_TIMEOUT_SECONDS,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    return connection


connection = create_connection()

