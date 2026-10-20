"""Regression tests for the safe, one-command local demo launcher."""

# AI-use disclosure: ChatGPT helped draft demo-launcher safety regression tests.
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_demo


class DemoLauncherTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.demo_database = self.root / "warungwise-demo.db"
        self.path_patch = patch.object(run_demo, "DEFAULT_DATABASE_PATH", self.demo_database)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)

    def test_creates_an_isolated_populated_demo(self):
        primary_database = self.root / "warungwise.db"
        primary_database.write_bytes(b"UNCHANGED PERSONAL INVENTORY")

        status, count = run_demo.prepare_demo_database()
        self.assertEqual(status, "seeded")
        self.assertGreater(count, 0)
        self.assertTrue(self.demo_database.is_file())
        self.assertEqual(primary_database.read_bytes(), b"UNCHANGED PERSONAL INVENTORY")

        with sqlite3.connect(self.demo_database) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM products").fetchone()[0],
                count,
            )
            self.assertGreater(
                connection.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0],
                0,
            )

    def test_existing_demo_changes_are_preserved(self):
        run_demo.prepare_demo_database()
        with sqlite3.connect(self.demo_database) as connection:
            connection.execute(
                "UPDATE products SET name = ? WHERE id = (SELECT MIN(id) FROM products)",
                ("Edited sample name",),
            )
            connection.commit()

        status, count = run_demo.prepare_demo_database()
        self.assertEqual(status, "existing_demo_reused")
        self.assertGreater(count, 0)

        with sqlite3.connect(self.demo_database) as connection:
            name = connection.execute(
                "SELECT name FROM products ORDER BY id LIMIT 1"
            ).fetchone()[0]
        self.assertEqual(name, "Edited sample name")

    def test_empty_initialized_demo_gets_seeded_safely(self):
        from init_db import initialize_database

        initialize_database(database_path=self.demo_database)
        status, count = run_demo.prepare_demo_database()
        self.assertEqual(status, "seeded")
        self.assertGreater(count, 0)

    def test_corrupt_demo_is_refused_not_replaced(self):
        corrupt_bytes = b"invalid SQLite sample"
        self.demo_database.write_bytes(corrupt_bytes)
        with self.assertRaises((sqlite3.DatabaseError, RuntimeError)):
            run_demo.prepare_demo_database()
        self.assertEqual(self.demo_database.read_bytes(), corrupt_bytes)


if __name__ == "__main__":
    unittest.main()
