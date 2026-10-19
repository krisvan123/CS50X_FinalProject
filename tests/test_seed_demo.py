"""Tests for the isolated fictional WarungWise demo dataset."""

# AI-use disclosure: ChatGPT assisted with drafting these dataset tests.
# Review the fixtures and assertions before relying on them for submission.
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import create_app
from seed_demo import DEMO_PRODUCTS, DEMO_SALES, seed_demo_database


class WarungWiseDemoSeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "warungwise-demo.db"

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_demo_seed_has_realistic_scenarios_and_balanced_ledgers(self) -> None:
        result = seed_demo_database(self.database_path)

        expected_batches = sum(len(product["batches"]) for product in DEMO_PRODUCTS)
        self.assertEqual(result["status"], "seeded")
        self.assertEqual(result["products"], len(DEMO_PRODUCTS))
        self.assertEqual(result["stock_batches"], expected_batches)
        self.assertEqual(result["sales"], len(DEMO_SALES))
        self.assertEqual(
            result["stock_operations"],
            expected_batches + len(DEMO_SALES) + 2,
        )

        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM v_batch_balance_audit WHERE difference <> 0"
            ).fetchone()[0], 0)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM v_sale_item_allocation_audit WHERE difference <> 0"
            ).fetchone()[0], 0)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM stock_batches "
                "WHERE quantity_remaining > 0 AND expiry_date < date('now', 'localtime')"
            ).fetchone()[0], 1)
            self.assertGreaterEqual(connection.execute(
                """
                SELECT COUNT(*) FROM stock_batches
                WHERE quantity_remaining > 0
                  AND expiry_date >= date('now', 'localtime')
                  AND expiry_date <= date('now', 'localtime', '+30 days')
                """
            ).fetchone()[0], 3)
            self.assertGreater(connection.execute(
                "SELECT COUNT(*) FROM sales s JOIN stock_operations op "
                "ON op.id = s.operation_id WHERE op.business_date = date('now', 'localtime')"
            ).fetchone()[0], 0)
            self.assertEqual(connection.execute(
                "SELECT quantity_remaining FROM stock_batches "
                "JOIN products ON products.id = stock_batches.product_id "
                "WHERE products.sku = 'WW-DEMO-SUGAR-001'"
            ).fetchone()[0], 7)
        finally:
            connection.close()

    def test_running_seed_twice_is_a_safe_no_op(self) -> None:
        first = seed_demo_database(self.database_path)
        second = seed_demo_database(self.database_path)

        self.assertEqual(first["status"], "seeded")
        self.assertEqual(second["status"], "already_seeded")
        self.assertEqual(first["products"], second["products"])
        self.assertEqual(first["stock_batches"], second["stock_batches"])
        self.assertEqual(first["sales"], second["sales"])
        self.assertEqual(first["stock_operations"], second["stock_operations"])

    def test_refuses_to_mix_demo_data_with_an_existing_inventory(self) -> None:
        seed_demo_database(self.database_path)
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(
                """
                INSERT INTO products (
                    name, sku, unit, cost_price, selling_price,
                    minimum_stock, lead_time_days, safety_stock, tracks_expiry
                ) VALUES ('Real Shop Product', 'REAL-001', 'pack', 1000, 1500, 2, 2, 1, 0)
                """
            )
            connection.commit()
        finally:
            connection.close()

        with self.assertRaisesRegex(ValueError, "already contains records"):
            seed_demo_database(self.database_path)

        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM products").fetchone()[0], len(DEMO_PRODUCTS) + 1)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM products WHERE sku = 'REAL-001'"
            ).fetchone()[0], 1)
        finally:
            connection.close()

    def test_read_only_public_demo_displays_a_clear_banner(self) -> None:
        seed_demo_database(self.database_path)
        app = create_app({
            "TESTING": True,
            "SECRET_KEY": "demo-readonly-test-only",
            "DATABASE": str(self.database_path),
            "DEMO_READ_ONLY": True,
        })
        response = app.test_client().get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Public demo", response.data)
        self.assertIn(b"Read-only", response.data)
        self.assertIn(b"fictional sample records", response.data)

    def test_read_only_public_demo_rejects_writes_without_changing_data(self) -> None:
        seed_demo_database(self.database_path)
        app = create_app({
            "TESTING": True,
            "SECRET_KEY": "demo-readonly-test-only",
            "DATABASE": str(self.database_path),
            "DEMO_READ_ONLY": True,
        })
        client = app.test_client()

        settings_response = client.post(
            "/settings", data={"expiry_warning_days": "7"}
        )
        product_response = client.post(
            "/products/new",
            data={
                "name": "Injected Public Product",
                "sku": "PUBLIC-INJECTED-001",
                "category": "Test",
                "unit": "pack",
                "cost_price": "1000",
                "selling_price": "1500",
                "minimum_stock": "2",
                "lead_time_days": "2",
                "safety_stock": "1",
                "tracks_expiry": "0",
            },
        )
        self.assertEqual(settings_response.status_code, 403)
        self.assertEqual(product_response.status_code, 403)

        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(
                connection.execute(
                    "SELECT expiry_warning_days FROM app_settings WHERE id = 1"
                ).fetchone()[0],
                30,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM products").fetchone()[0],
                len(DEMO_PRODUCTS),
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM products WHERE sku = 'PUBLIC-INJECTED-001'"
                ).fetchone()[0],
                0,
            )
        finally:
            connection.close()

    def test_vercel_public_assets_match_local_source_files(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        asset_paths = (
            Path("css/styles.css"),
            Path("js/app.js"),
        )

        for relative_path in asset_paths:
            with self.subTest(asset=str(relative_path)):
                local_asset = project_root / "static" / relative_path
                public_asset = project_root / "public" / "static" / relative_path
                self.assertTrue(local_asset.is_file(), str(local_asset))
                self.assertTrue(public_asset.is_file(), str(public_asset))
                self.assertEqual(public_asset.read_bytes(), local_asset.read_bytes())

    def test_primary_pages_render_with_seeded_demo_database(self) -> None:
        seed_demo_database(self.database_path)
        app = create_app({
            "TESTING": True,
            "SECRET_KEY": "demo-seed-test-only",
            "DATABASE": str(self.database_path),
        })
        client = app.test_client()

        for path in (
            "/", "/products", "/batches", "/sales", "/stock-actions/new",
            "/movements", "/recommendations", "/reports", "/settings",
        ):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200, response.data.decode("utf-8", errors="replace"))


if __name__ == "__main__":
    unittest.main()
