"""Launch a local WarungWise demo against a separate, fictional SQLite database.

No production/local-shop records are read or modified. An existing demo database
is reused rather than reset, so sample edits made during a walkthrough persist.
"""

# AI-use disclosure: ChatGPT assisted with this optional, safe demo launcher.
from __future__ import annotations

import os
import sqlite3
import sys

from seed_demo import DEFAULT_DATABASE_PATH, seed_demo_database


def prepare_demo_database() -> tuple[str, int]:
    """Seed a missing/empty demo DB, or reuse an existing populated demo DB."""
    database_path = DEFAULT_DATABASE_PATH.resolve()
    if database_path.exists() and not database_path.is_file():
        raise OSError(f"Demo database path is not a file: {database_path}")

    if not database_path.exists():
        result = seed_demo_database(database_path)
        return str(result["status"]), int(result["products"])

    # Inspect without writing. Do not call the seed function on a populated DB,
    # because a user may have modified the sample records while exploring.
    with sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise RuntimeError("The existing demo database failed the SQLite integrity check.")

        product_count = int(connection.execute("SELECT COUNT(*) FROM products").fetchone()[0])

    if product_count == 0:
        result = seed_demo_database(database_path)
        return str(result["status"]), int(result["products"])

    return "existing_demo_reused", product_count


def main() -> int:
    if os.environ.get("VERCEL") == "1":
        print("Use this launcher locally, not in a Vercel function.", file=sys.stderr)
        return 1

    try:
        status, product_count = prepare_demo_database()
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as error:
        print(f"Could not prepare the demo: {error}", file=sys.stderr)
        print("Your normal inventory database was not modified.", file=sys.stderr)
        return 1

    demo_path = DEFAULT_DATABASE_PATH.resolve()
    os.environ["WARUNGWISE_DATABASE"] = str(demo_path)
    os.environ["WARUNGWISE_DEMO_READ_ONLY"] = "false"
    os.environ["WARUNGWISE_DEMO_SAMPLE"] = "true"

    from app import create_app

    application = create_app()
    print(f"Demo database: {demo_path}", flush=True)
    print(f"Demo status: {status} ({product_count} products)", flush=True)
    print("This is fictional sample data, separate from instance/warungwise.db.", flush=True)
    print("Open http://127.0.0.1:5000 and press Ctrl+C to stop.", flush=True)
    application.run(host="127.0.0.1", port=5000, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
