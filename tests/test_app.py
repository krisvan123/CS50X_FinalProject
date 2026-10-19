"""Smoke tests for the Phase 4 Flask foundation.

Run from the repository root with: python -m unittest discover -s tests
These tests use temporary SQLite databases and do not touch local user data.
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import create_app
from init_db import initialize_database


class WarungWiseAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "warungwise.db"
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-only-secret",
                "DATABASE": str(self.database_path),
            }
        )
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_home_explains_first_time_setup(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 503)
        self.assertIn(b"python init_db.py", response.data)
        self.assertIn(b"Initialize the database", response.data)

    def test_health_reports_setup_required_without_database(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {"status": "setup_required"})

    def test_empty_dashboard_loads_after_initialization(self) -> None:
        initialize_database(database_path=self.database_path)

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Inventory overview", response.data)
        self.assertIn(b"data-testid=\"metric-active-products\"", response.data)
        self.assertIn(b"No stock movements yet", response.data)
        self.assertIn(b"Rp 0", response.data)

    def test_dashboard_uses_database_product_counts(self) -> None:
        initialize_database(database_path=self.database_path)

        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(
                """
                INSERT INTO products (
                    name, unit, cost_price, selling_price, minimum_stock,
                    lead_time_days, safety_stock, tracks_expiry
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("Demo Mineral Water", "bottle", 2000, 3000, 5, 2, 3, 0),
            )
            connection.commit()
        finally:
            connection.close()

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'data-testid="metric-active-products"', response.data)
        self.assertIn(b'data-testid="metric-low-stock"', response.data)
        self.assertGreaterEqual(
            response.data.count(b'<p class="metric-value">1</p>'),
            2,
        )

    def test_health_reports_ready_database_and_foreign_keys(self) -> None:
        initialize_database(database_path=self.database_path)

        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_unknown_route_uses_safe_not_found_page(self) -> None:
        response = self.client.get("/route-that-does-not-exist")

        self.assertEqual(response.status_code, 404)
        self.assertIn(b"Page not found", response.data)
        self.assertNotIn(b"Traceback", response.data)


if __name__ == "__main__":
    unittest.main()
