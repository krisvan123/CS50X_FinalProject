"""Automated tests for the WarungWise foundation and product management.

Run from the repository root with: python -m unittest discover -s tests -v
All tests use temporary SQLite databases and do not touch local user data.
"""
from __future__ import annotations

import re
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



    def _product_form_values(self, **overrides: str) -> dict[str, str]:
        values = {
            "name": "Mineral Water", "sku": "MW-001", "category": "Beverages",
            "unit": "bottle", "cost_price": "2000", "selling_price": "3000",
            "minimum_stock": "5", "lead_time_days": "2", "safety_stock": "3",
            "tracks_expiry": "0",
        }
        values.update(overrides)
        return values

    def _post_with_csrf(
        self, page_path: str, post_path: str, values: dict[str, str],
        *, follow_redirects: bool = False,
    ):
        page = self.client.get(page_path)
        self.assertEqual(page.status_code, 200, page.data.decode("utf-8", errors="replace"))
        match = re.search(rb'name="csrf_token"\s+value="([^"]+)"', page.data)
        self.assertIsNotNone(match, "Expected the form page to include a CSRF token.")
        payload = dict(values)
        payload["csrf_token"] = match.group(1).decode("ascii")
        return self.client.post(post_path, data=payload, follow_redirects=follow_redirects)

    def _create_product(self, **overrides: str) -> int:
        if not self.database_path.exists():
            initialize_database(database_path=self.database_path)
        response = self._post_with_csrf(
            "/products/new", "/products/new", self._product_form_values(**overrides)
        )
        self.assertEqual(response.status_code, 302, response.data.decode("utf-8", errors="replace"))
        connection = sqlite3.connect(self.database_path)
        try:
            product_id = connection.execute(
                "SELECT id FROM products ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
        finally:
            connection.close()
        return int(product_id)

    def _add_receipt_batch(self, product_id: int) -> None:
        from datetime import date

        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            today = date.today().isoformat()
            cursor = connection.execute(
                """
                INSERT INTO stock_operations (operation_type, request_token, business_date)
                VALUES ('receipt', ?, ?)
                """,
                (f"test-receipt-{product_id}", today),
            )
            operation_id = cursor.lastrowid
            cursor = connection.execute(
                """
                INSERT INTO stock_batches (
                    product_id, receipt_operation_id, received_date,
                    expiry_date, quantity_received, unit_cost
                )
                VALUES (?, ?, ?, NULL, 5, 1000)
                """,
                (product_id, operation_id, today),
            )
            batch_id = cursor.lastrowid
            connection.execute(
                """
                INSERT INTO stock_movements (
                    operation_id, product_id, batch_id, quantity_delta
                ) VALUES (?, ?, ?, 5)
                """,
                (operation_id, product_id, batch_id),
            )
            connection.commit()
        finally:
            connection.close()

    def test_product_catalog_explains_setup_when_database_is_missing(self) -> None:
        response = self.client.get("/products")
        self.assertEqual(response.status_code, 503)
        self.assertIn(b"python init_db.py", response.data)

    def test_product_list_loads_after_database_initialization(self) -> None:
        initialize_database(database_path=self.database_path)
        response = self.client.get("/products")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Product management", response.data)
        self.assertIn(b"No products yet", response.data)
        self.assertIn(b"Add product", response.data)

    def test_product_creation_trims_text_and_normalizes_sku(self) -> None:
        initialize_database(database_path=self.database_path)
        response = self._post_with_csrf(
            "/products/new", "/products/new",
            self._product_form_values(name="  Mineral Water  ", sku=" mw-001 ",
                                      category=" Beverages ", unit=" bottle "),
        )
        self.assertEqual(response.status_code, 302)
        connection = sqlite3.connect(self.database_path)
        try:
            row = connection.execute("SELECT name, sku, category, unit FROM products").fetchone()
        finally:
            connection.close()
        self.assertEqual(row, ("Mineral Water", "MW-001", "Beverages", "bottle"))

    def test_product_creation_rejects_invalid_prices(self) -> None:
        initialize_database(database_path=self.database_path)
        response = self._post_with_csrf(
            "/products/new", "/products/new",
            self._product_form_values(cost_price="-1", selling_price="0"),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Cost price must be a whole number", response.data)
        self.assertIn(b"Selling price must be a whole number", response.data)
        connection = sqlite3.connect(self.database_path)
        try:
            count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 0)

    def test_product_creation_rejects_blank_name(self) -> None:
        initialize_database(database_path=self.database_path)
        response = self._post_with_csrf(
            "/products/new", "/products/new", self._product_form_values(name="   ")
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Enter a product name", response.data)

    def test_product_sku_must_be_unique_without_case_sensitivity(self) -> None:
        initialize_database(database_path=self.database_path)
        self._create_product(sku="MW-001")
        response = self._post_with_csrf(
            "/products/new", "/products/new",
            self._product_form_values(name="Different Water", sku="mw-001"),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"SKU is already used", response.data)
        connection = sqlite3.connect(self.database_path)
        try:
            count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 1)

    def test_product_search_matches_name_sku_and_category(self) -> None:
        initialize_database(database_path=self.database_path)
        self._create_product(name="Mineral Water", sku="MW-001", category="Beverages")
        for query in ("Mineral", "mw-001", "Beverages"):
            with self.subTest(query=query):
                response = self.client.get("/products", query_string={"q": query})
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"Mineral Water", response.data)

    def test_product_category_filter_is_applied(self) -> None:
        initialize_database(database_path=self.database_path)
        self._create_product(name="Mineral Water", sku="MW-001", category="Beverages")
        self._create_product(name="Laundry Soap", sku="LS-002", category="Household")
        response = self.client.get(
            "/products", query_string={"category": "Household", "status": "active"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Laundry Soap", response.data)
        self.assertNotIn(b"Mineral Water", response.data)

    def test_product_edit_updates_current_fields(self) -> None:
        initialize_database(database_path=self.database_path)
        product_id = self._create_product()
        response = self._post_with_csrf(
            f"/products/{product_id}/edit", f"/products/{product_id}/edit",
            self._product_form_values(
                name="Updated Mineral Water", selling_price="3500", minimum_stock="8"
            ),
        )
        self.assertEqual(response.status_code, 302)
        connection = sqlite3.connect(self.database_path)
        try:
            row = connection.execute(
                "SELECT name, selling_price, minimum_stock FROM products WHERE id = ?",
                (product_id,),
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(row, ("Updated Mineral Water", 3500, 8))

    def test_product_can_be_archived_when_no_stock_remains(self) -> None:
        initialize_database(database_path=self.database_path)
        product_id = self._create_product()
        response = self._post_with_csrf(
            "/products", f"/products/{product_id}/archive", {}, follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Historical records have been preserved", response.data)
        connection = sqlite3.connect(self.database_path)
        try:
            archived = connection.execute(
                "SELECT is_archived FROM products WHERE id = ?", (product_id,)
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(archived, 1)

    def test_product_cannot_be_archived_while_batch_stock_remains(self) -> None:
        initialize_database(database_path=self.database_path)
        product_id = self._create_product()
        self._add_receipt_batch(product_id)
        response = self._post_with_csrf(
            "/products", f"/products/{product_id}/archive", {}, follow_redirects=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"cannot be archived while stock remains", response.data)
        connection = sqlite3.connect(self.database_path)
        try:
            archived = connection.execute(
                "SELECT is_archived FROM products WHERE id = ?", (product_id,)
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(archived, 0)

    def test_expiry_tracking_cannot_change_after_a_batch_exists(self) -> None:
        initialize_database(database_path=self.database_path)
        product_id = self._create_product(tracks_expiry="0")
        self._add_receipt_batch(product_id)
        response = self._post_with_csrf(
            f"/products/{product_id}/edit", f"/products/{product_id}/edit",
            self._product_form_values(tracks_expiry="1"),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"cannot be changed after a stock batch", response.data)
        connection = sqlite3.connect(self.database_path)
        try:
            tracks_expiry = connection.execute(
                "SELECT tracks_expiry FROM products WHERE id = ?", (product_id,)
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(tracks_expiry, 0)

    def test_state_changing_form_rejects_missing_csrf_token(self) -> None:
        initialize_database(database_path=self.database_path)
        response = self.client.post("/products/new", data=self._product_form_values())
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Invalid request", response.data)


if __name__ == "__main__":
    unittest.main()
