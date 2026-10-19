"""Create a new local WarungWise SQLite database from schema.sql.

This script deliberately refuses to overwrite an existing database.
It uses only Python's standard library.
"""
from __future__ import annotations

from pathlib import Path
import sqlite3


PROJECT_ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = PROJECT_ROOT / "schema.sql"
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "instance" / "warungwise.db"


def initialize_database(
    database_path: Path = DEFAULT_DATABASE_PATH,
    schema_path: Path = SCHEMA_PATH,
) -> Path:
    """Initialize a new database and return its path.

    Raises:
        FileNotFoundError: If the schema file does not exist.
        FileExistsError: If the target database already exists.
        RuntimeError: If SQLite integrity checks fail.
    """
    database_path = Path(database_path).expanduser()
    schema_path = Path(schema_path).expanduser()

    if not schema_path.is_file():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")

    if database_path.exists():
        raise FileExistsError(
            f"Database already exists and will not be overwritten: {database_path}"
        )

    database_path.parent.mkdir(parents=True, exist_ok=True)
    database_created = False

    try:
        connection = sqlite3.connect(database_path)
        database_created = True
        try:
            # SQLite foreign-key enforcement is connection-specific.
            connection.execute("PRAGMA foreign_keys = ON")
            schema_sql = schema_path.read_text(encoding="utf-8")
            connection.executescript(schema_sql)

            foreign_key_violations = connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            if foreign_key_violations:
                raise RuntimeError(
                    f"Foreign-key check failed: {foreign_key_violations}"
                )

            integrity_result = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity_result is None or integrity_result[0] != "ok":
                raise RuntimeError(f"SQLite integrity check failed: {integrity_result}")
        finally:
            connection.close()
    except Exception:
        # Remove only the database created by this failed invocation.
        if database_created:
            for suffix in ("", "-journal", "-wal", "-shm"):
                Path(f"{database_path}{suffix}").unlink(missing_ok=True)
        raise

    return database_path


def main() -> int:
    try:
        database_path = initialize_database()
    except (OSError, RuntimeError, sqlite3.Error) as error:
        print(f"Database initialization failed: {error}")
        return 1

    print(f"WarungWise database initialized at: {database_path}")
    print("No demo records were inserted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
