"""Automated tests for the WarungWise foundation and product management.

Run from the repository root with: python -m unittest discover -s tests -v
All tests use temporary SQLite databases and do not touch local user data.
"""

# AI-use disclosure: ChatGPT assisted with drafting selected test cases; review
# the scenarios and expected outcomes before relying on them for submission.
from __future__ import annotations

import csv
import re
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

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


    def test_browser_security_headers_and_dynamic_no_store_policy(self) -> None:
        initialize_database(database_path=self.database_path)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(
            response.headers.get("Referrer-Policy"),
            "strict-origin-when-cross-origin",
        )
        self.assertEqual(
            response.headers.get("Permissions-Policy"),
            "camera=(), microphone=(), geolocation=()",
        )
        csp = response.headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")

        static_response = self.client.get("/static/css/styles.css")
        self.assertEqual(static_response.status_code, 200)
        self.assertEqual(static_response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertNotEqual(static_response.headers.get("Cache-Control"), "no-store")

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
        request_match = re.search(rb'name="request_token"\s+value="([^"]+)"', page.data)
        if request_match and "request_token" not in payload:
            payload["request_token"] = request_match.group(1).decode("ascii")
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
            f"/products/{product_id}/edit",
            f"/products/{product_id}/archive",
            {},
            follow_redirects=True,
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



    def test_extremely_long_numeric_input_is_rejected(self) -> None:
        initialize_database(database_path=self.database_path)
        response = self._post_with_csrf(
            "/products/new",
            "/products/new",
            self._product_form_values(cost_price="9" * 5000),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Cost price must be a whole number", response.data)
        connection = sqlite3.connect(self.database_path)
        try:
            count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 0)



    def _batch_form_values(self, product_id: int, **overrides: str) -> dict[str, str]:
        from datetime import date

        values = {
            "product_id": str(product_id),
            "received_date": date.today().isoformat(),
            "expiry_date": "",
            "quantity_received": "5",
            "unit_cost": "1800",
            "note": "Delivery note 001",
        }
        values.update(overrides)
        return values

    def test_batch_register_explains_setup_when_database_is_missing(self) -> None:
        self.assertEqual(self.client.get("/batches").status_code, 503)

    def test_movements_ledger_explains_setup_when_database_is_missing(self) -> None:
        self.assertEqual(self.client.get("/movements").status_code, 503)

    def test_receiving_stock_creates_batch_and_ledger_movement_atomically(self) -> None:
        from datetime import date

        initialize_database(database_path=self.database_path)
        product_id = self._create_product(tracks_expiry="0")
        response = self._post_with_csrf(
            "/batches/new", "/batches/new", self._batch_form_values(product_id)
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/batches")

        connection = sqlite3.connect(self.database_path)
        try:
            batch = connection.execute(
                """
                SELECT quantity_received, quantity_remaining, unit_cost, received_date, expiry_date
                FROM stock_batches WHERE product_id = ?
                """,
                (product_id,),
            ).fetchone()
            movement = connection.execute(
                """
                SELECT sm.quantity_delta, op.operation_type, op.note, op.business_date
                FROM stock_movements AS sm
                JOIN stock_operations AS op ON op.id = sm.operation_id
                WHERE sm.product_id = ?
                """,
                (product_id,),
            ).fetchone()
        finally:
            connection.close()

        self.assertEqual(batch, (5, 5, 1800, date.today().isoformat(), None))
        self.assertEqual(
            movement, (5, "receipt", "Delivery note 001", date.today().isoformat())
        )

        batches_page = self.client.get("/batches")
        self.assertEqual(batches_page.status_code, 200)
        self.assertIn(b"Mineral Water", batches_page.data)
        self.assertIn(b"Available", batches_page.data)

        movements_page = self.client.get("/movements")
        self.assertEqual(movements_page.status_code, 200)
        self.assertIn(b"Stock received", movements_page.data)
        self.assertIn(b"Delivery note 001", movements_page.data)

    def test_expiry_tracked_product_requires_expiry_date(self) -> None:
        initialize_database(database_path=self.database_path)
        product_id = self._create_product(tracks_expiry="1")
        response = self._post_with_csrf(
            "/batches/new", "/batches/new",
            self._batch_form_values(product_id, expiry_date=""),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"An expiry date is required", response.data)
        connection = sqlite3.connect(self.database_path)
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM stock_batches WHERE product_id = ?", (product_id,)
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 0)

    def test_product_without_expiry_tracking_rejects_expiry_date(self) -> None:
        from datetime import date, timedelta

        initialize_database(database_path=self.database_path)
        product_id = self._create_product(tracks_expiry="0")
        expiry = (date.today() + timedelta(days=30)).isoformat()
        response = self._post_with_csrf(
            "/batches/new", "/batches/new",
            self._batch_form_values(product_id, expiry_date=expiry),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"does not track expiry dates", response.data)

    def test_stock_receipt_rejects_zero_or_negative_quantity(self) -> None:
        initialize_database(database_path=self.database_path)
        product_id = self._create_product()
        for quantity in ("0", "-2", "1.5", ""):
            with self.subTest(quantity=quantity):
                response = self._post_with_csrf(
                    "/batches/new", "/batches/new",
                    self._batch_form_values(product_id, quantity_received=quantity),
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn(
                    b"Quantity must be a whole number greater than zero", response.data
                )
        connection = sqlite3.connect(self.database_path)
        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM stock_batches WHERE product_id = ?", (product_id,)
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(count, 0)

    def test_stock_receipt_rejects_expiry_before_received_date(self) -> None:
        from datetime import date, timedelta

        initialize_database(database_path=self.database_path)
        product_id = self._create_product(tracks_expiry="1")
        received = date.today().isoformat()
        expiry = (date.today() - timedelta(days=1)).isoformat()
        response = self._post_with_csrf(
            "/batches/new", "/batches/new",
            self._batch_form_values(
                product_id, received_date=received, expiry_date=expiry
            ),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Expiry date cannot be earlier than the received date", response.data)

    def test_stock_receipt_rejects_archived_product(self) -> None:
        initialize_database(database_path=self.database_path)
        product_id = self._create_product()
        self._post_with_csrf("/products", f"/products/{product_id}/archive", {})
        response = self._post_with_csrf(
            "/batches/new", "/batches/new", self._batch_form_values(product_id)
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Archived or missing products cannot receive stock", response.data)

    def test_stock_receipt_rejects_missing_csrf_token(self) -> None:
        initialize_database(database_path=self.database_path)
        response = self.client.post("/batches/new", data={
            "product_id": "1",
            "received_date": "2026-01-01",
            "expiry_date": "",
            "quantity_received": "5",
            "unit_cost": "1000",
            "note": "",
        })
        self.assertEqual(response.status_code, 400)

    def test_expired_batch_is_flagged_in_the_batch_register(self) -> None:
        from datetime import date, timedelta

        initialize_database(database_path=self.database_path)
        product_id = self._create_product(tracks_expiry="1")
        received = (date.today() - timedelta(days=20)).isoformat()
        expiry = (date.today() - timedelta(days=2)).isoformat()
        response = self._post_with_csrf(
            "/batches/new", "/batches/new",
            self._batch_form_values(
                product_id, received_date=received, expiry_date=expiry
            ),
        )
        self.assertEqual(response.status_code, 302)
        page = self.client.get("/batches?status=expired")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Expired", page.data)
        self.assertIn(b'data-testid="batch-expired-count">1', page.data)

    def test_movement_search_and_type_filter_are_applied(self) -> None:
        initialize_database(database_path=self.database_path)
        product_id = self._create_product(name="Mineral Water")
        self._post_with_csrf(
            "/batches/new", "/batches/new", self._batch_form_values(product_id)
        )
        response = self.client.get(
            "/movements", query_string={"q": "Mineral", "type": "receipt"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Mineral Water", response.data)
        self.assertIn(b"Stock received", response.data)
        response = self.client.get(
            "/movements", query_string={"q": "Mineral", "type": "sale"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No stock movements found", response.data)



    def _sale_form_values(self, product_id: int, **overrides: str) -> dict[str, str]:
        from datetime import date

        values = {
            "product_id": str(product_id),
            "business_date": date.today().isoformat(),
            "quantity": "1",
            "note": "Counter sale",
        }
        values.update(overrides)
        return values

    def _receive_batch_via_form(
        self, product_id: int, *, received_date: str, expiry_date: str,
        quantity: str, unit_cost: str = "1800",
    ) -> None:
        response = self._post_with_csrf(
            "/batches/new",
            "/batches/new",
            self._batch_form_values(
                product_id,
                received_date=received_date,
                expiry_date=expiry_date,
                quantity_received=quantity,
                unit_cost=unit_cost,
            ),
        )
        self.assertEqual(response.status_code, 302, response.data.decode("utf-8", errors="replace"))

    def test_sales_pages_explain_setup_and_render_empty_history(self) -> None:
        self.assertEqual(self.client.get("/sales").status_code, 503)
        initialize_database(database_path=self.database_path)
        response = self.client.get("/sales")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Sales history", response.data)
        self.assertIn(b"No sales recorded yet", response.data)
        self.assertIn(b"Record your first sale", response.data)

    def test_sale_uses_fefo_and_records_each_batch_movement(self) -> None:
        from datetime import date, timedelta

        initialize_database(database_path=self.database_path)
        product_id = self._create_product(tracks_expiry="1")
        today = date.today()
        first_received = (today - timedelta(days=20)).isoformat()
        second_received = (today - timedelta(days=10)).isoformat()
        soonest_expiry = (today + timedelta(days=5)).isoformat()
        later_expiry = (today + timedelta(days=15)).isoformat()

        self._receive_batch_via_form(
            product_id, received_date=first_received, expiry_date=soonest_expiry,
            quantity="4", unit_cost="1500",
        )
        self._receive_batch_via_form(
            product_id, received_date=second_received, expiry_date=later_expiry,
            quantity="3", unit_cost="1600",
        )

        response = self._post_with_csrf(
            "/sales/new", "/sales/new", self._sale_form_values(product_id, quantity="5")
        )
        self.assertEqual(response.status_code, 302, response.data.decode("utf-8", errors="replace"))
        self.assertEqual(response.headers["Location"], "/sales")

        connection = sqlite3.connect(self.database_path)
        try:
            batch_balances = connection.execute(
                """
                SELECT expiry_date, quantity_remaining
                FROM stock_batches WHERE product_id = ?
                ORDER BY expiry_date ASC
                """,
                (product_id,),
            ).fetchall()
            sale_row = connection.execute(
                """
                SELECT si.quantity, si.unit_selling_price, op.operation_type
                FROM sale_items AS si
                JOIN sales AS s ON s.id = si.sale_id
                JOIN stock_operations AS op ON op.id = s.operation_id
                WHERE si.product_id = ?
                """,
                (product_id,),
            ).fetchone()
            sale_movements = connection.execute(
                """
                SELECT b.expiry_date, sm.quantity_delta
                FROM stock_movements AS sm
                JOIN stock_operations AS op ON op.id = sm.operation_id
                JOIN stock_batches AS b ON b.id = sm.batch_id
                WHERE sm.product_id = ? AND op.operation_type = 'sale'
                ORDER BY b.expiry_date ASC
                """,
                (product_id,),
            ).fetchall()
        finally:
            connection.close()

        self.assertEqual(
            batch_balances,
            [(soonest_expiry, 0), (later_expiry, 2)],
        )
        self.assertEqual(sale_row, (5, 3000, "sale"))
        self.assertEqual(sale_movements, [(soonest_expiry, -4), (later_expiry, -1)])

        response = self.client.get("/sales")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Rp 15.000", response.data)
        self.assertIn(b"Counter sale", response.data)

    def test_sale_rejects_quantity_above_sellable_stock(self) -> None:
        initialize_database(database_path=self.database_path)
        product_id = self._create_product()
        response = self._post_with_csrf(
            "/sales/new", "/sales/new", self._sale_form_values(product_id, quantity="1")
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Available quantity: 0", response.data)

        connection = sqlite3.connect(self.database_path)
        try:
            sales_count = connection.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
            movements_count = connection.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(sales_count, 0)
        self.assertEqual(movements_count, 0)

    def test_sale_cannot_allocate_expired_batch(self) -> None:
        from datetime import date, timedelta

        initialize_database(database_path=self.database_path)
        product_id = self._create_product(tracks_expiry="1")
        self._receive_batch_via_form(
            product_id,
            received_date=(date.today() - timedelta(days=10)).isoformat(),
            expiry_date=(date.today() - timedelta(days=1)).isoformat(),
            quantity="5",
        )
        response = self._post_with_csrf(
            "/sales/new", "/sales/new", self._sale_form_values(product_id, quantity="1")
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Available quantity: 0", response.data)

    def test_historical_sale_cannot_use_a_batch_received_later(self) -> None:
        from datetime import date, timedelta

        initialize_database(database_path=self.database_path)
        product_id = self._create_product(tracks_expiry="0")
        self._receive_batch_via_form(
            product_id,
            received_date=date.today().isoformat(),
            expiry_date="",
            quantity="5",
        )
        earlier_date = (date.today() - timedelta(days=1)).isoformat()
        response = self._post_with_csrf(
            "/sales/new", "/sales/new",
            self._sale_form_values(product_id, business_date=earlier_date, quantity="1"),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Available quantity: 0", response.data)

    def test_sale_rejects_zero_quantity_and_future_business_date(self) -> None:
        from datetime import date, timedelta

        initialize_database(database_path=self.database_path)
        product_id = self._create_product()
        for payload in (
            self._sale_form_values(product_id, quantity="0"),
            self._sale_form_values(
                product_id, business_date=(date.today() + timedelta(days=1)).isoformat()
            ),
        ):
            response = self._post_with_csrf("/sales/new", "/sales/new", payload)
            self.assertEqual(response.status_code, 400)

    def test_sale_form_rejects_missing_csrf_token(self) -> None:
        initialize_database(database_path=self.database_path)
        response = self.client.post("/sales/new", data={
            "product_id": "1",
            "business_date": "2026-01-01",
            "quantity": "1",
            "note": "",
        })
        self.assertEqual(response.status_code, 400)

    def test_sales_search_filters_product_history(self) -> None:
        initialize_database(database_path=self.database_path)
        first_id = self._create_product(name="Mineral Water")
        second_id = self._create_product(name="Laundry Soap", sku="LS-002")
        self._post_with_csrf(
            "/batches/new", "/batches/new", self._batch_form_values(first_id)
        )
        self._post_with_csrf(
            "/batches/new", "/batches/new", self._batch_form_values(second_id)
        )
        self._post_with_csrf(
            "/sales/new", "/sales/new",
            self._sale_form_values(first_id, quantity="1"), follow_redirects=True,
        )
        self._post_with_csrf(
            "/sales/new", "/sales/new",
            self._sale_form_values(second_id, quantity="1"), follow_redirects=True,
        )

        response = self.client.get("/sales", query_string={"q": "Mineral"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Mineral Water", response.data)
        self.assertNotIn(b"Laundry Soap", response.data)


    def test_dashboard_shows_low_stock_and_expiry_watchlists(self) -> None:
        from datetime import date, timedelta

        initialize_database(database_path=self.database_path)
        product_id = self._create_product(
            name="Expiry Yoghurt",
            tracks_expiry="1",
            minimum_stock="2",
        )
        expiry_date = (date.today() + timedelta(days=2)).isoformat()
        self._post_with_csrf(
            "/batches/new",
            "/batches/new",
            self._batch_form_values(
                product_id,
                expiry_date=expiry_date,
                quantity_received="1",
            ),
            follow_redirects=True,
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Low-stock watchlist", response.data)
        self.assertIn(b"Expiry watchlist", response.data)
        self.assertIn(b"Expiry Yoghurt", response.data)
        self.assertIn(b"2 days left", response.data)
        self.assertIn(b"1", response.data)


    def test_recommendations_explains_empty_and_missing_sales_history(self) -> None:
        initialize_database(database_path=self.database_path)
        product_id = self._create_product(name="Rice Crackers")

        response = self.client.get("/recommendations")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Restock recommendations", response.data)
        self.assertIn(b"Rice Crackers", response.data)
        self.assertIn(b"No sales history", response.data)
        self.assertIn(b"Estimate withheld", response.data)
        self.assertIn(b"data-testid=\"restock-history-count\">1", response.data)
        self.assertNotIn(b"data-testid=\"restock-product-count\">1", response.data)

    def test_recommendations_calculate_restock_from_sales_and_sellable_stock(self) -> None:
        from datetime import date, timedelta

        initialize_database(database_path=self.database_path)
        product_id = self._create_product(
            name="Bottled Tea",
            tracks_expiry="0",
            lead_time_days="5",
            safety_stock="3",
        )
        today = date.today()
        first_sale = today - timedelta(days=14)
        self._receive_batch_via_form(
            product_id,
            received_date=first_sale.isoformat(),
            expiry_date="",
            quantity="20",
        )

        for sale_day in (first_sale, today - timedelta(days=7), today):
            response = self._post_with_csrf(
                "/sales/new",
                "/sales/new",
                self._sale_form_values(
                    product_id,
                    business_date=sale_day.isoformat(),
                    quantity="6",
                ),
                follow_redirects=True,
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.get("/recommendations")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Bottled Tea", response.data)
        self.assertIn(b"18 bottle", response.data)
        self.assertIn(b"1.2 bottle/day", response.data)
        self.assertIn(b"15 observed calendar day(s)", response.data)
        self.assertIn(b"9 bottle", response.data)
        self.assertIn(b"7", response.data)
        self.assertIn(b"Restock suggested", response.data)

        connection = sqlite3.connect(self.database_path)
        try:
            remaining = connection.execute(
                "SELECT quantity_remaining FROM stock_batches WHERE product_id = ?",
                (product_id,),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(remaining, 2)

    def test_recommendations_withhold_estimate_for_less_than_seven_days(self) -> None:
        from datetime import date, timedelta

        initialize_database(database_path=self.database_path)
        product_id = self._create_product(
            name="New Snack",
            tracks_expiry="0",
            lead_time_days="4",
            safety_stock="2",
        )
        today = date.today()
        self._receive_batch_via_form(
            product_id,
            received_date=(today - timedelta(days=1)).isoformat(),
            expiry_date="",
            quantity="8",
        )
        response = self._post_with_csrf(
            "/sales/new",
            "/sales/new",
            self._sale_form_values(
                product_id,
                business_date=today.isoformat(),
                quantity="1",
            ),
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.get("/recommendations")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"New Snack", response.data)
        self.assertIn(b"Building history", response.data)
        self.assertIn(b"Only 1 calendar day(s)", response.data)
        self.assertIn(b"At least 7 days are required", response.data)
        self.assertIn(b"Estimate withheld", response.data)
        self.assertNotIn(b"data-testid=\"restock-product-count\">1", response.data)


    def test_reports_explain_setup_and_render_empty_period(self) -> None:
        self.assertEqual(self.client.get("/reports").status_code, 503)
        initialize_database(database_path=self.database_path)

        response = self.client.get("/reports")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Reports & analytics", response.data)
        self.assertIn(b"No sales in this reporting period", response.data)
        self.assertIn(b"Sales transactions", response.data)
        self.assertIn(b"Current inventory snapshot", response.data)

    def test_reports_filter_sales_and_calculate_revenue_and_daily_trend(self) -> None:
        from datetime import date, timedelta

        initialize_database(database_path=self.database_path)
        product_id = self._create_product(name="Bottled Tea")
        today = date.today()
        first_sale = today - timedelta(days=14)
        self._receive_batch_via_form(
            product_id,
            received_date=first_sale.isoformat(),
            expiry_date="",
            quantity="20",
        )

        for sale_date, quantity in (
            (first_sale, "2"),
            (today - timedelta(days=7), "4"),
            (today, "1"),
        ):
            response = self._post_with_csrf(
                "/sales/new",
                "/sales/new",
                self._sale_form_values(
                    product_id,
                    business_date=sale_date.isoformat(),
                    quantity=quantity,
                ),
                follow_redirects=True,
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.get(
            "/reports",
            query_string={
                "start_date": first_sale.isoformat(),
                "end_date": today.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Rp 21.000", response.data)
        self.assertIn(b"Bottled Tea", response.data)
        self.assertIn(b"Gross revenue trend", response.data)
        self.assertIn(b"3", response.data)
        self.assertIn(b"13", response.data)

    def test_sales_csv_contains_only_selected_business_dates(self) -> None:
        from datetime import date, timedelta

        initialize_database(database_path=self.database_path)
        product_id = self._create_product(name="Tea Bottle")
        today = date.today()
        yesterday = today - timedelta(days=1)
        self._receive_batch_via_form(
            product_id,
            received_date=yesterday.isoformat(),
            expiry_date="",
            quantity="10",
        )
        for sale_date in (yesterday, today):
            response = self._post_with_csrf(
                "/sales/new",
                "/sales/new",
                self._sale_form_values(product_id, business_date=sale_date.isoformat()),
                follow_redirects=True,
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.get(
            "/reports/export/sales",
            query_string={"start_date": today.isoformat(), "end_date": today.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/csv")
        self.assertIn('attachment; filename="warungwise_sales_', response.headers["Content-Disposition"])
        csv_text = response.get_data(as_text=True).lstrip("\\ufeff")
        rows = list(csv.reader(csv_text.splitlines()))
        self.assertEqual(len(rows), 2, "Only the header and today's transaction should be exported.")
        self.assertIn("Gross Total (IDR)", rows[0])
        self.assertEqual(rows[1][3], "Tea Bottle")
        self.assertEqual(rows[1][1], today.isoformat())

    def test_movement_csv_exports_receipt_and_sale_ledger_rows(self) -> None:
        from datetime import date

        initialize_database(database_path=self.database_path)
        product_id = self._create_product(name="Tea Bottle")
        today = date.today()
        self._receive_batch_via_form(
            product_id,
            received_date=today.isoformat(),
            expiry_date="",
            quantity="10",
        )
        self._post_with_csrf(
            "/sales/new",
            "/sales/new",
            self._sale_form_values(product_id, business_date=today.isoformat(), quantity="2"),
        )

        response = self.client.get(
            "/reports/export/movements",
            query_string={"start_date": today.isoformat(), "end_date": today.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        csv_text = response.get_data(as_text=True).lstrip("\\ufeff")
        rows = list(__import__("csv").reader(csv_text.splitlines()))
        self.assertEqual(len(rows), 3)
        self.assertIn("Quantity Delta", rows[0])
        self.assertEqual({row[3] for row in rows[1:]}, {"receipt", "sale"})

    def test_inventory_csv_protects_formula_like_product_text(self) -> None:
        from datetime import date

        initialize_database(database_path=self.database_path)
        product_id = self._create_product(name="=2+2", sku="=SKU-1")
        self._receive_batch_via_form(
            product_id,
            received_date=date.today().isoformat(),
            expiry_date="",
            quantity="3",
        )

        response = self.client.get("/reports/export/inventory")

        self.assertEqual(response.status_code, 200)
        csv_text = response.get_data(as_text=True).lstrip("\\ufeff")
        rows = list(__import__("csv").reader(csv_text.splitlines()))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][1], "'=2+2")
        self.assertEqual(rows[1][2], "'=SKU-1")



    def test_concurrent_receipt_submissions_with_same_token_are_serialized(self) -> None:
        """Two simultaneous POSTs of one receipt create only one operation."""
        product_id = self._create_product()
        first_client = self.app.test_client()
        form = first_client.get("/batches/new")
        self.assertEqual(form.status_code, 200)
        csrf = re.search(rb'name="csrf_token"\s+value="([^"]+)"', form.data).group(1).decode()
        request_token = re.search(
            rb'name="request_token"\s+value="([^"]+)"', form.data
        ).group(1).decode()

        second_client = self.app.test_client()
        with second_client.session_transaction() as saved_session:
            saved_session["_csrf_token"] = csrf

        from datetime import date
        payload = {
            "csrf_token": csrf,
            "request_token": request_token,
            "product_id": str(product_id),
            "received_date": date.today().isoformat(),
            "expiry_date": "",
            "quantity_received": "4",
            "unit_cost": "1250",
            "note": "Concurrent retry",
        }
        barrier = Barrier(2)

        def submit(client):
            barrier.wait(timeout=5)
            return client.post("/batches/new", data=payload)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(submit, first_client)
            second_future = pool.submit(submit, second_client)
            responses = [first_future.result(timeout=10), second_future.result(timeout=10)]

        self.assertEqual(
            sorted(response.status_code for response in responses),
            [302, 302],
        )
        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM stock_operations WHERE request_token = ?",
                (request_token,),
            ).fetchone()[0], 1)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM stock_batches WHERE product_id = ?",
                (product_id,),
            ).fetchone()[0], 1)
            self.assertEqual(connection.execute(
                "SELECT quantity_remaining FROM stock_batches WHERE product_id = ?",
                (product_id,),
            ).fetchone()[0], 4)
            self.assertEqual(connection.execute(
                "SELECT difference FROM v_batch_balance_audit WHERE product_id = ?",
                (product_id,),
            ).fetchone()[0], 0)
        finally:
            connection.close()

    def test_stock_receipt_duplicate_submission_uses_same_request_token(self) -> None:
        product_id = self._create_product()
        from datetime import date

        form = self.client.get("/batches/new")
        self.assertEqual(form.status_code, 200)
        csrf = re.search(rb'name="csrf_token"\s+value="([^"]+)"', form.data).group(1).decode()
        token = re.search(rb'name="request_token"\s+value="([^"]+)"', form.data).group(1).decode()
        payload = {
            "csrf_token": csrf, "request_token": token, "product_id": str(product_id),
            "received_date": date.today().isoformat(), "expiry_date": "",
            "quantity_received": "4", "unit_cost": "1250", "note": "One delivery",
        }
        self.assertEqual(self.client.post("/batches/new", data=payload).status_code, 302)
        self.assertEqual(self.client.post("/batches/new", data=payload).status_code, 302)
        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM stock_batches WHERE product_id = ?", (product_id,)).fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM stock_operations WHERE request_token = ?", (token,)).fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT quantity_remaining FROM stock_batches WHERE product_id = ?", (product_id,)).fetchone()[0], 4)
        finally:
            connection.close()


    def test_backdated_sale_cannot_make_later_batch_balance_negative(self) -> None:
        from datetime import date, timedelta

        product_id = self._create_product()
        receipt_date = date.today() - timedelta(days=4)
        prior_sale_date = date.today() - timedelta(days=2)
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            cursor = connection.execute(
                """
                INSERT INTO stock_operations (operation_type, request_token, business_date)
                VALUES ('receipt', ?, ?)
                """, ("historical-safe-receipt", receipt_date.isoformat()),
            )
            receipt_operation_id = cursor.lastrowid
            cursor = connection.execute(
                """
                INSERT INTO stock_batches (
                    product_id, receipt_operation_id, received_date, expiry_date,
                    quantity_received, quantity_remaining, unit_cost
                ) VALUES (?, ?, ?, NULL, 10, 0, 1000)
                """, (product_id, receipt_operation_id, receipt_date.isoformat()),
            )
            batch_id = cursor.lastrowid
            connection.execute(
                "INSERT INTO stock_movements (operation_id, product_id, batch_id, quantity_delta) VALUES (?, ?, ?, 10)",
                (receipt_operation_id, product_id, batch_id),
            )
            cursor = connection.execute(
                """
                INSERT INTO stock_operations (operation_type, request_token, business_date)
                VALUES ('sale', ?, ?)
                """, ("historical-safe-sale", prior_sale_date.isoformat()),
            )
            sale_operation_id = cursor.lastrowid
            cursor = connection.execute("INSERT INTO sales (operation_id) VALUES (?)", (sale_operation_id,))
            sale_id = cursor.lastrowid
            cursor = connection.execute(
                """
                INSERT INTO sale_items (sale_id, product_id, quantity, unit_selling_price)
                VALUES (?, ?, 8, 3000)
                """, (sale_id, product_id),
            )
            sale_item_id = cursor.lastrowid
            connection.execute(
                """
                INSERT INTO stock_movements (
                    operation_id, product_id, batch_id, sale_item_id, quantity_delta
                ) VALUES (?, ?, ?, ?, -8)
                """, (sale_operation_id, product_id, batch_id, sale_item_id),
            )
            cursor = connection.execute(
                """
                INSERT INTO stock_operations (
                    operation_type, request_token, business_date, reason
                ) VALUES ('adjustment_in', ?, ?, ?)
                """, ("historical-safe-adjust", date.today().isoformat(), "Later physical count"),
            )
            adjustment_operation_id = cursor.lastrowid
            connection.execute(
                """
                INSERT INTO stock_movements (
                    operation_id, product_id, batch_id, quantity_delta
                ) VALUES (?, ?, ?, 5)
                """, (adjustment_operation_id, product_id, batch_id),
            )
            connection.commit()
        finally:
            connection.close()

        response = self._post_with_csrf(
            "/sales/new", "/sales/new",
            {
                "product_id": str(product_id),
                "business_date": receipt_date.isoformat(),
                "quantity": "3",
                "note": "Late entry must not break the historical ledger",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Available quantity: 2", response.data)
        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(connection.execute(
                "SELECT quantity_remaining FROM stock_batches WHERE id = ?", (batch_id,)
            ).fetchone()[0], 7)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 1)
            self.assertEqual(connection.execute(
                "SELECT difference FROM v_batch_balance_audit WHERE batch_id = ?", (batch_id,)
            ).fetchone()[0], 0)
        finally:
            connection.close()

    def test_sale_duplicate_submission_does_not_decrement_stock_twice(self) -> None:
        from datetime import date

        product_id = self._create_product()
        self._add_receipt_batch(product_id)
        form = self.client.get("/sales/new")
        self.assertEqual(form.status_code, 200)
        csrf = re.search(rb'name="csrf_token"\s+value="([^"]+)"', form.data).group(1).decode()
        token = re.search(rb'name="request_token"\s+value="([^"]+)"', form.data).group(1).decode()
        payload = {
            "csrf_token": csrf, "request_token": token, "product_id": str(product_id),
            "business_date": date.today().isoformat(), "quantity": "2", "note": "One checkout",
        }
        self.assertEqual(self.client.post("/sales/new", data=payload).status_code, 302)
        self.assertEqual(self.client.post("/sales/new", data=payload).status_code, 302)
        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT quantity_remaining FROM stock_batches WHERE product_id = ?", (product_id,)).fetchone()[0], 3)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM stock_movements WHERE quantity_delta < 0").fetchone()[0], 1)
        finally:
            connection.close()

    def _post_stock_action(self, batch_id: int, **overrides: str):
        from datetime import date
        values = {
            "batch_id": str(batch_id), "operation_type": "disposal",
            "business_date": date.today().isoformat(), "quantity": "1",
            "reason": "Expired goods", "note": "",
        }
        values.update(overrides)
        return self._post_with_csrf("/stock-actions/new", "/stock-actions/new", values)

    def test_disposal_reduces_batch_and_records_reason_and_cost_basis(self) -> None:
        from datetime import date
        product_id = self._create_product()
        self._add_receipt_batch(product_id)
        connection = sqlite3.connect(self.database_path)
        try:
            batch_id = connection.execute("SELECT id FROM stock_batches WHERE product_id = ?", (product_id,)).fetchone()[0]
        finally:
            connection.close()

        response = self._post_stock_action(batch_id, quantity="2", reason="Expired goods")
        self.assertEqual(response.status_code, 302)
        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(connection.execute("SELECT quantity_remaining FROM stock_batches WHERE id = ?", (batch_id,)).fetchone()[0], 3)
            row = connection.execute(
                """
                SELECT op.operation_type, op.reason, sm.quantity_delta
                FROM stock_movements sm JOIN stock_operations op ON op.id = sm.operation_id
                WHERE sm.batch_id = ? AND op.operation_type = 'disposal'
                """, (batch_id,),
            ).fetchone()
            self.assertEqual(row, ("disposal", "Expired goods", -2))
            audit = connection.execute("SELECT difference, receipt_difference FROM v_batch_balance_audit WHERE batch_id = ?", (batch_id,)).fetchone()
            self.assertEqual(audit, (0, 0))
        finally:
            connection.close()
        report = self.client.get("/reports", query_string={"start_date": date.today().isoformat(), "end_date": date.today().isoformat()})
        self.assertEqual(report.status_code, 200)
        self.assertIn(b"Recorded disposal value", report.data)
        self.assertIn(b"Rp 2.000", report.data)

    def test_stock_count_inbound_and_outbound_corrections_are_auditable(self) -> None:
        product_id = self._create_product()
        self._add_receipt_batch(product_id)
        connection = sqlite3.connect(self.database_path)
        try:
            batch_id = connection.execute("SELECT id FROM stock_batches WHERE product_id = ?", (product_id,)).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(self._post_stock_action(batch_id, operation_type="adjustment_in", quantity="3", reason="Physical count found extra stock").status_code, 302)
        self.assertEqual(self._post_stock_action(batch_id, operation_type="adjustment_out", quantity="2", reason="Damaged during count").status_code, 302)
        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(connection.execute("SELECT quantity_remaining FROM stock_batches WHERE id = ?", (batch_id,)).fetchone()[0], 6)
            ledger = connection.execute(
                """
                SELECT op.operation_type, sm.quantity_delta, op.reason
                FROM stock_movements sm JOIN stock_operations op ON op.id = sm.operation_id
                WHERE sm.batch_id = ? AND op.operation_type IN ('adjustment_in', 'adjustment_out')
                ORDER BY sm.id
                """, (batch_id,),
            ).fetchall()
            self.assertEqual(ledger, [("adjustment_in", 3, "Physical count found extra stock"), ("adjustment_out", -2, "Damaged during count")])
            self.assertEqual(connection.execute("SELECT difference FROM v_batch_balance_audit WHERE batch_id = ?", (batch_id,)).fetchone()[0], 0)
        finally:
            connection.close()

    def test_disposal_cannot_overdraw_batch_and_requires_reason(self) -> None:
        product_id = self._create_product()
        self._add_receipt_batch(product_id)
        connection = sqlite3.connect(self.database_path)
        try:
            batch_id = connection.execute("SELECT id FROM stock_batches WHERE product_id = ?", (product_id,)).fetchone()[0]
        finally:
            connection.close()
        overdraw = self._post_stock_action(batch_id, quantity="6", reason="Too much")
        self.assertEqual(overdraw.status_code, 400)
        self.assertIn(b"Only 5", overdraw.data)
        missing_reason = self._post_stock_action(batch_id, quantity="1", reason="   ")
        self.assertEqual(missing_reason.status_code, 400)
        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(connection.execute("SELECT quantity_remaining FROM stock_batches WHERE id = ?", (batch_id,)).fetchone()[0], 5)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM stock_operations WHERE operation_type = 'disposal'").fetchone()[0], 0)
        finally:
            connection.close()


    def test_stock_action_duplicate_submission_does_not_apply_twice(self) -> None:
        product_id = self._create_product()
        self._add_receipt_batch(product_id)
        form = self.client.get("/stock-actions/new")
        self.assertEqual(form.status_code, 200)
        csrf = re.search(rb'name="csrf_token"\s+value="([^"]+)"', form.data).group(1).decode()
        token = re.search(rb'name="request_token"\s+value="([^"]+)"', form.data).group(1).decode()
        connection = sqlite3.connect(self.database_path)
        try:
            batch_id = connection.execute(
                "SELECT id FROM stock_batches WHERE product_id = ?", (product_id,)
            ).fetchone()[0]
        finally:
            connection.close()
        from datetime import date
        payload = {
            "csrf_token": csrf, "request_token": token, "batch_id": str(batch_id),
            "operation_type": "disposal", "business_date": date.today().isoformat(),
            "quantity": "2", "reason": "Expired goods", "note": "Discard once",
        }
        first = self.client.post("/stock-actions/new", data=payload)
        second = self.client.post("/stock-actions/new", data=payload)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(connection.execute(
                "SELECT quantity_remaining FROM stock_batches WHERE id = ?", (batch_id,)
            ).fetchone()[0], 3)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM stock_operations WHERE request_token = ?", (token,)
            ).fetchone()[0], 1)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM stock_movements WHERE operation_id = (SELECT id FROM stock_operations WHERE request_token = ?)",
                (token,),
            ).fetchone()[0], 1)
        finally:
            connection.close()

    def test_expiry_warning_window_can_be_changed_in_settings(self) -> None:
        initialize_database(database_path=self.database_path)
        page = self.client.get("/settings")
        self.assertEqual(page.status_code, 200)
        token = re.search(rb'name="csrf_token"\s+value="([^"]+)"', page.data).group(1).decode()
        response = self.client.post("/settings", data={"csrf_token": token, "expiry_warning_days": "14"})
        self.assertEqual(response.status_code, 302)
        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(connection.execute("SELECT expiry_warning_days FROM app_settings WHERE id = 1").fetchone()[0], 14)
        finally:
            connection.close()

    def test_settings_reject_invalid_expiry_warning_window(self) -> None:
        initialize_database(database_path=self.database_path)
        page = self.client.get("/settings")
        token = re.search(rb'name="csrf_token"\s+value="([^"]+)"', page.data).group(1).decode()
        response = self.client.post("/settings", data={"csrf_token": token, "expiry_warning_days": "999"})
        self.assertEqual(response.status_code, 400)
        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(connection.execute("SELECT expiry_warning_days FROM app_settings WHERE id = 1").fetchone()[0], 30)
        finally:
            connection.close()

    def test_reports_reject_invalid_date_ranges_and_unknown_exports(self) -> None:
        from datetime import date, timedelta

        initialize_database(database_path=self.database_path)
        today = date.today()
        yesterday = today - timedelta(days=1)

        reversed_period = self.client.get(
            "/reports",
            query_string={"start_date": today.isoformat(), "end_date": yesterday.isoformat()},
        )
        self.assertEqual(reversed_period.status_code, 400)

        future_period = self.client.get(
            "/reports",
            query_string={
                "start_date": today.isoformat(),
                "end_date": (today + timedelta(days=1)).isoformat(),
            },
        )
        self.assertEqual(future_period.status_code, 400)

        long_period = self.client.get(
            "/reports",
            query_string={
                "start_date": (today - timedelta(days=366)).isoformat(),
                "end_date": today.isoformat(),
            },
        )
        self.assertEqual(long_period.status_code, 400)

        self.assertEqual(self.client.get("/reports/export/unknown").status_code, 404)


if __name__ == "__main__":
    unittest.main()
