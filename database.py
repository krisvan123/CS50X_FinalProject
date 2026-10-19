"""SQLite connection helpers for WarungWise."""

# AI-use disclosure: ChatGPT assisted with drafting/refining this connection helper.
# The project author should understand request-scoped connections and teardown behavior.
from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import Flask, current_app, g


def get_db() -> sqlite3.Connection:
    """Return the current request's SQLite connection.

    Foreign-key checks are enabled for every connection because SQLite does
    not enable them by default. Connections are cached on Flask's g object
    and closed when the application context ends.
    """
    if "db" not in g:
        database_path = Path(current_app.config["DATABASE"])

        if not database_path.is_file():
            raise FileNotFoundError(
                "The WarungWise database has not been initialized. "
                "Run python init_db.py from the project root."
            )

        connection = sqlite3.connect(
            str(database_path),
            timeout=5.0,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
        except Exception:
            connection.close()
            raise

        g.db = connection

    return g.db


def close_db(_error: BaseException | None = None) -> None:
    """Rollback any unfinished transaction and close the request connection."""
    connection = g.pop("db", None)

    if connection is not None:
        try:
            if connection.in_transaction:
                connection.rollback()
        finally:
            connection.close()


def init_app(app: Flask) -> None:
    """Register connection cleanup with the Flask application."""
    app.teardown_appcontext(close_db)
