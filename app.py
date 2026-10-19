"""WarungWise Flask application entry point and product-management workflows."""
from __future__ import annotations

import hmac
import logging
import math
import os
import re
import secrets
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from flask import (
    Flask, abort, current_app, flash, jsonify, redirect, render_template,
    request, session, url_for,
)

import database




PRODUCT_TEXT_LIMITS = {"name": 120, "sku": 50, "category": 80, "unit": 30}


def _get_csrf_token() -> str:
    """Return a session-bound token for protecting state-changing forms."""
    token = session.get("_csrf_token")
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def _csrf_is_valid() -> bool:
    """Validate a form token without exposing token details to the client."""
    expected = session.get("_csrf_token")
    supplied = request.form.get("csrf_token", "")
    return (
        isinstance(expected, str)
        and bool(supplied)
        and hmac.compare_digest(expected, supplied)
    )


def _empty_product_form() -> dict[str, str]:
    """Provide safe initial values for the create-product form."""
    return {
        "name": "", "sku": "", "category": "", "unit": "piece",
        "cost_price": "0", "selling_price": "1", "minimum_stock": "0",
        "lead_time_days": "1", "safety_stock": "0", "tracks_expiry": "0",
    }


def _product_form_from_row(product: sqlite3.Row) -> dict[str, str]:
    """Convert a database row into display-safe form values."""
    fields = (
        "name", "sku", "category", "unit", "cost_price", "selling_price",
        "minimum_stock", "lead_time_days", "safety_stock", "tracks_expiry",
    )
    return {field: "" if product[field] is None else str(product[field]) for field in fields}


def _parse_product_form(form: Any) -> tuple[dict[str, str], dict[str, str], dict[str, Any]]:
    """Normalize product form values and return field-level validation errors."""
    text_fields = ("name", "sku", "category", "unit")
    form_data = {field: str(form.get(field, "")).strip() for field in text_fields}
    form_data["sku"] = form_data["sku"].upper()
    form_data["tracks_expiry"] = str(form.get("tracks_expiry", "0")).strip()

    numeric_fields = (
        "cost_price", "selling_price", "minimum_stock", "lead_time_days", "safety_stock"
    )
    for field in numeric_fields:
        form_data[field] = str(form.get(field, "")).strip()

    errors: dict[str, str] = {}
    if not form_data["name"]:
        errors["name"] = "Enter a product name."
    if not form_data["unit"]:
        errors["unit"] = "Enter an inventory unit."
    for field, maximum in PRODUCT_TEXT_LIMITS.items():
        if len(form_data[field]) > maximum:
            errors[field] = f"Use no more than {maximum} characters."

    constraints = {
        "cost_price": (0, "Cost price must be a whole number of zero or more."),
        "selling_price": (1, "Selling price must be a whole number greater than zero."),
        "minimum_stock": (0, "Minimum stock must be a whole number of zero or more."),
        "lead_time_days": (1, "Lead time must be a whole number of at least one day."),
        "safety_stock": (0, "Safety stock must be a whole number of zero or more."),
    }
    parsed_numbers: dict[str, int] = {}
    sqlite_integer_max = 9_223_372_036_854_775_807
    for field, (minimum, message) in constraints.items():
        raw_value = form_data[field]
        if not re.fullmatch(r"[0-9]+", raw_value):
            errors[field] = message
            continue
        try:
            value = int(raw_value)
        except ValueError:
            errors[field] = message
            continue
        if value < minimum or value > sqlite_integer_max:
            errors[field] = message
            continue
        parsed_numbers[field] = value

    if form_data["tracks_expiry"] not in {"0", "1"}:
        errors["tracks_expiry"] = "Choose whether this product tracks expiry dates."

    product_data: dict[str, Any] = {
        "name": form_data["name"],
        "sku": form_data["sku"] or None,
        "category": form_data["category"] or None,
        "unit": form_data["unit"],
    }
    product_data.update(parsed_numbers)
    if form_data["tracks_expiry"] in {"0", "1"}:
        product_data["tracks_expiry"] = int(form_data["tracks_expiry"])
    return form_data, errors, product_data



def _load_dashboard_data(connection: sqlite3.Connection) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build a dashboard summary from database records only."""
    today = date.today()
    today_iso = today.isoformat()

    settings = connection.execute(
        "SELECT expiry_warning_days FROM app_settings WHERE id = 1"
    ).fetchone()

    if settings is None:
        raise sqlite3.DatabaseError("The application settings row is missing.")

    warning_days = int(settings["expiry_warning_days"])
    warning_end_iso = (today + timedelta(days=warning_days)).isoformat()

    active_products = connection.execute(
        "SELECT COUNT(*) AS total FROM products WHERE is_archived = 0"
    ).fetchone()["total"]

    low_stock_products = connection.execute(
        """
        SELECT COUNT(*) AS total
        FROM (
            SELECT
                p.id,
                p.minimum_stock,
                COALESCE(
                    SUM(
                        CASE
                            WHEN b.quantity_remaining > 0
                                 AND (b.expiry_date IS NULL OR b.expiry_date >= ?)
                            THEN b.quantity_remaining
                            ELSE 0
                        END
                    ),
                    0
                ) AS sellable_quantity
            FROM products AS p
            LEFT JOIN stock_batches AS b ON b.product_id = p.id
            WHERE p.is_archived = 0
            GROUP BY p.id, p.minimum_stock
            HAVING sellable_quantity <= p.minimum_stock
        )
        """,
        (today_iso,),
    ).fetchone()["total"]

    near_expiry_batches = connection.execute(
        """
        SELECT COUNT(*) AS total
        FROM stock_batches
        WHERE quantity_remaining > 0
          AND expiry_date IS NOT NULL
          AND expiry_date >= ?
          AND expiry_date <= ?
        """,
        (today_iso, warning_end_iso),
    ).fetchone()["total"]

    expired_batches = connection.execute(
        """
        SELECT COUNT(*) AS total
        FROM stock_batches
        WHERE quantity_remaining > 0
          AND expiry_date IS NOT NULL
          AND expiry_date < ?
        """,
        (today_iso,),
    ).fetchone()["total"]

    # Dashboard watchlists are derived from current batch records, not cached totals.
    low_stock_rows = connection.execute(
        """
        SELECT
            p.id,
            p.name,
            p.sku,
            p.unit,
            p.minimum_stock,
            COALESCE(
                SUM(
                    CASE
                        WHEN b.quantity_remaining > 0
                             AND (b.expiry_date IS NULL OR b.expiry_date >= ?)
                        THEN b.quantity_remaining
                        ELSE 0
                    END
                ),
                0
            ) AS sellable_quantity
        FROM products AS p
        LEFT JOIN stock_batches AS b ON b.product_id = p.id
        WHERE p.is_archived = 0
        GROUP BY p.id, p.name, p.sku, p.unit, p.minimum_stock
        HAVING sellable_quantity <= p.minimum_stock
        ORDER BY sellable_quantity ASC, p.name COLLATE NOCASE ASC
        LIMIT 6
        """,
        (today_iso,),
    ).fetchall()
    low_stock_items = [dict(row) for row in low_stock_rows]

    expiry_rows = connection.execute(
        """
        SELECT
            b.id AS batch_id,
            p.name AS product_name,
            p.sku,
            p.unit,
            b.quantity_remaining,
            b.expiry_date
        FROM stock_batches AS b
        JOIN products AS p ON p.id = b.product_id
        WHERE b.quantity_remaining > 0
          AND b.expiry_date IS NOT NULL
          AND b.expiry_date <= ?
        ORDER BY
            CASE WHEN b.expiry_date < ? THEN 0 ELSE 1 END,
            b.expiry_date ASC,
            b.id ASC
        LIMIT 6
        """,
        (warning_end_iso, today_iso),
    ).fetchall()
    expiry_alerts: list[dict[str, Any]] = []
    for row in expiry_rows:
        alert = dict(row)
        expiry_day = date.fromisoformat(alert["expiry_date"])
        alert["is_expired"] = expiry_day < today
        alert["days_to_expiry"] = (expiry_day - today).days
        expiry_alerts.append(alert)

    sales_today = connection.execute(
        """
        SELECT
            COUNT(DISTINCT s.id) AS transaction_count,
            COALESCE(SUM(si.quantity * si.unit_selling_price), 0) AS revenue
        FROM sales AS s
        JOIN stock_operations AS op ON op.id = s.operation_id
        JOIN sale_items AS si ON si.sale_id = s.id
        WHERE op.business_date = ?
        """,
        (today_iso,),
    ).fetchone()

    recent_rows = connection.execute(
        """
        SELECT
            sm.id,
            p.name AS product_name,
            op.operation_type,
            op.occurred_at_utc,
            sm.quantity_delta,
            b.expiry_date
        FROM stock_movements AS sm
        JOIN stock_operations AS op ON op.id = sm.operation_id
        JOIN products AS p ON p.id = sm.product_id
        JOIN stock_batches AS b ON b.id = sm.batch_id
        ORDER BY op.occurred_at_utc DESC, sm.id DESC
        LIMIT 8
        """
    ).fetchall()

    operation_labels = {
        "receipt": "Stock received",
        "sale": "Sale",
        "disposal": "Disposal",
        "adjustment_out": "Stock correction",
        "adjustment_in": "Stock correction",
    }

    recent_movements: list[dict[str, Any]] = []
    for row in recent_rows:
        movement = dict(row)
        movement["operation_label"] = operation_labels.get(
            movement["operation_type"], "Stock movement"
        )
        delta = int(movement["quantity_delta"])
        movement["quantity_display"] = f"+{delta}" if delta > 0 else str(delta)
        recent_movements.append(movement)

    stats: dict[str, Any] = {
        "active_products": int(active_products),
        "low_stock_products": int(low_stock_products),
        "near_expiry_batches": int(near_expiry_batches),
        "expired_batches": int(expired_batches),
        "sales_today_count": int(sales_today["transaction_count"] or 0),
        "sales_today_revenue": int(sales_today["revenue"] or 0),
        "expiry_warning_days": warning_days,
        "business_date": today_iso,
    }

    return stats, recent_movements, low_stock_items, expiry_alerts


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Create and configure the WarungWise Flask application."""
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        # Never embed an actual secret in source control. A stable value can
        # be supplied through WARUNGWISE_SECRET_KEY when the application needs it.
        SECRET_KEY=os.environ.get("WARUNGWISE_SECRET_KEY") or os.urandom(32),
        DATABASE=str(Path(app.instance_path) / "warungwise.db"),
        MAX_CONTENT_LENGTH=1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    if test_config is not None:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    database.init_app(app)

    @app.template_filter("idr")
    def format_idr(value: Any) -> str:
        """Format a whole-rupiah amount without floating-point conversion."""
        try:
            amount = int(value or 0)
        except (TypeError, ValueError):
            amount = 0
        return "Rp " + f"{amount:,}".replace(",", ".")

    @app.get("/")
    def index():
        database_path = Path(current_app.config["DATABASE"])

        if not database_path.is_file():
            return render_template(
                "setup.html",
                title="Initialize database",
            ), 503

        try:
            connection = database.get_db()
            stats, recent_movements, low_stock_items, expiry_alerts = _load_dashboard_data(connection)
        except (sqlite3.Error, FileNotFoundError):
            current_app.logger.exception("Unable to load the WarungWise dashboard.")
            return render_template(
                "error.html",
                title="Dashboard unavailable",
                error_code=503,
                message=(
                    "The dashboard could not read the database. Check that the "
                    "database was initialized from the current schema, then try again."
                ),
            ), 503

        return render_template(
            "index.html",
            title="Inventory overview",
            stats=stats,
            recent_movements=recent_movements,
            low_stock_items=low_stock_items,
            expiry_alerts=expiry_alerts,
        )

    @app.context_processor
    def provide_csrf_token():
        """Expose a session-bound CSRF token generator to templates."""
        return {"csrf_token": _get_csrf_token}

    @app.get("/products")
    def products():
        """List, search, and filter active or archived product records."""
        database_path = Path(current_app.config["DATABASE"])
        if not database_path.is_file():
            return render_template("setup.html", title="Initialize database"), 503

        search_query = request.args.get("q", "").strip()[:100]
        status = request.args.get("status", "active")
        if status not in {"active", "archived", "all"}:
            status = "active"
        category = request.args.get("category", "").strip()[:PRODUCT_TEXT_LIMITS["category"]]

        conditions: list[str] = []
        parameters: list[Any] = []
        if status != "all":
            conditions.append("p.is_archived = ?")
            parameters.append(1 if status == "archived" else 0)
        if search_query:
            conditions.append(
                "(p.name LIKE ? COLLATE NOCASE "
                "OR COALESCE(p.sku, '') LIKE ? COLLATE NOCASE "
                "OR COALESCE(p.category, '') LIKE ? COLLATE NOCASE)"
            )
            wildcard_query = f"%{search_query}%"
            parameters.extend([wildcard_query, wildcard_query, wildcard_query])
        if category:
            conditions.append("p.category = ?")
            parameters.append(category)

        where_sql = " AND ".join(conditions) if conditions else "1 = 1"
        try:
            connection = database.get_db()
            product_rows = connection.execute(
                f"""
                SELECT p.*, COALESCE(SUM(b.quantity_remaining), 0) AS remaining_stock
                FROM products AS p
                LEFT JOIN stock_batches AS b ON b.product_id = p.id
                WHERE {where_sql}
                GROUP BY p.id
                ORDER BY p.is_archived ASC, p.name COLLATE NOCASE ASC
                LIMIT 250
                """,
                parameters,
            ).fetchall()
            category_rows = connection.execute(
                """
                SELECT DISTINCT category FROM products
                WHERE category IS NOT NULL AND length(trim(category)) > 0
                ORDER BY category COLLATE NOCASE
                """
            ).fetchall()
        except (sqlite3.Error, FileNotFoundError):
            current_app.logger.exception("Unable to load the product catalogue.")
            return render_template(
                "error.html",
                title="Product catalogue unavailable",
                error_code=503,
                message="The product catalogue could not be loaded. Check the local database setup and try again.",
            ), 503

        return render_template(
            "products/index.html",
            title="Product management",
            products=product_rows,
            categories=[row["category"] for row in category_rows],
            search_query=search_query,
            status=status,
            selected_category=category,
        )

    @app.route("/products/new", methods=["GET", "POST"])
    def new_product():
        """Create a product after server-side validation."""
        database_path = Path(current_app.config["DATABASE"])
        if not database_path.is_file():
            return render_template("setup.html", title="Initialize database"), 503

        if request.method == "GET":
            return render_template(
                "products/form.html",
                title="Add product",
                form_heading="Add a product",
                form_intro="Create a product record before receiving stock.",
                form_data=_empty_product_form(),
                errors={},
                is_edit=False,
                product_id=None,
            )

        if not _csrf_is_valid():
            abort(400)

        form_data, errors, product_data = _parse_product_form(request.form)
        connection = database.get_db()
        if not errors and product_data["sku"] is not None:
            duplicate = connection.execute(
                "SELECT 1 FROM products WHERE sku = ? COLLATE NOCASE",
                (product_data["sku"],),
            ).fetchone()
            if duplicate:
                errors["sku"] = "That SKU is already used by another product."

        if errors:
            return render_template(
                "products/form.html",
                title="Add product",
                form_heading="Add a product",
                form_intro="Review the highlighted fields and try again.",
                form_data=form_data,
                errors=errors,
                is_edit=False,
                product_id=None,
            ), 400

        try:
            connection.execute(
                """
                INSERT INTO products (
                    name, sku, category, unit, cost_price, selling_price,
                    minimum_stock, lead_time_days, safety_stock, tracks_expiry
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product_data["name"], product_data["sku"], product_data["category"],
                    product_data["unit"], product_data["cost_price"], product_data["selling_price"],
                    product_data["minimum_stock"], product_data["lead_time_days"],
                    product_data["safety_stock"], product_data["tracks_expiry"],
                ),
            )
            connection.commit()
        except sqlite3.IntegrityError as error:
            connection.rollback()
            if "sku" in str(error).lower():
                errors["sku"] = "That SKU is already used by another product."
                return render_template(
                    "products/form.html",
                    title="Add product",
                    form_heading="Add a product",
                    form_intro="Review the highlighted fields and try again.",
                    form_data=form_data,
                    errors=errors,
                    is_edit=False,
                    product_id=None,
                ), 400
            current_app.logger.exception("Product creation was rejected by the database.")
            return render_template(
                "error.html",
                title="Product could not be saved",
                error_code=400,
                message="The product could not be saved. Review its details and try again.",
            ), 400

        flash("Product created successfully.", "success")
        return redirect(url_for("products"))

    @app.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
    def edit_product(product_id: int):
        """Edit product details without rewriting historical transactions."""
        database_path = Path(current_app.config["DATABASE"])
        if not database_path.is_file():
            return render_template("setup.html", title="Initialize database"), 503

        connection = database.get_db()
        product = connection.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if product is None:
            abort(404)

        if request.method == "GET":
            return render_template(
                "products/form.html",
                title="Edit product",
                form_heading="Edit product",
                form_intro="Changes apply to the product's current settings. Historical sale prices remain unchanged.",
                form_data=_product_form_from_row(product),
                errors={},
                is_edit=True,
                product_id=product_id,
            )

        if not _csrf_is_valid():
            abort(400)

        form_data, errors, product_data = _parse_product_form(request.form)
        if not errors and product_data["sku"] is not None:
            duplicate = connection.execute(
                """
                SELECT 1 FROM products
                WHERE sku = ? COLLATE NOCASE AND id <> ?
                """,
                (product_data["sku"], product_id),
            ).fetchone()
            if duplicate:
                errors["sku"] = "That SKU is already used by another product."

        if not errors and product_data["tracks_expiry"] != int(product["tracks_expiry"]):
            has_batches = connection.execute(
                "SELECT 1 FROM stock_batches WHERE product_id = ? LIMIT 1",
                (product_id,),
            ).fetchone()
            if has_batches:
                errors["tracks_expiry"] = (
                    "Expiry tracking cannot be changed after a stock batch has been created."
                )

        if errors:
            return render_template(
                "products/form.html",
                title="Edit product",
                form_heading="Edit product",
                form_intro="Review the highlighted fields and try again.",
                form_data=form_data,
                errors=errors,
                is_edit=True,
                product_id=product_id,
            ), 400

        try:
            connection.execute(
                """
                UPDATE products
                SET name = ?, sku = ?, category = ?, unit = ?,
                    cost_price = ?, selling_price = ?, minimum_stock = ?,
                    lead_time_days = ?, safety_stock = ?, tracks_expiry = ?,
                    updated_at_utc = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                WHERE id = ?
                """,
                (
                    product_data["name"], product_data["sku"], product_data["category"],
                    product_data["unit"], product_data["cost_price"], product_data["selling_price"],
                    product_data["minimum_stock"], product_data["lead_time_days"],
                    product_data["safety_stock"], product_data["tracks_expiry"], product_id,
                ),
            )
            connection.commit()
        except sqlite3.IntegrityError as error:
            connection.rollback()
            if "sku" in str(error).lower():
                errors["sku"] = "That SKU is already used by another product."
                return render_template(
                    "products/form.html",
                    title="Edit product",
                    form_heading="Edit product",
                    form_intro="Review the highlighted fields and try again.",
                    form_data=form_data,
                    errors=errors,
                    is_edit=True,
                    product_id=product_id,
                ), 400
            current_app.logger.exception("Product update was rejected by the database.")
            return render_template(
                "error.html",
                title="Product could not be updated",
                error_code=400,
                message="The product could not be updated. Review its details and try again.",
            ), 400

        flash("Product updated successfully.", "success")
        return redirect(url_for("products"))

    @app.post("/products/<int:product_id>/archive")
    def archive_product(product_id: int):
        """Archive a product only when no batch has remaining quantity."""
        if not _csrf_is_valid():
            abort(400)

        database_path = Path(current_app.config["DATABASE"])
        if not database_path.is_file():
            return render_template("setup.html", title="Initialize database"), 503

        connection = database.get_db()
        product = connection.execute(
            "SELECT id, is_archived FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if product is None:
            abort(404)
        if product["is_archived"]:
            flash("This product is already archived.", "info")
            return redirect(url_for("products", status="archived"))

        remaining_stock = connection.execute(
            """
            SELECT COALESCE(SUM(quantity_remaining), 0) AS quantity
            FROM stock_batches
            WHERE product_id = ? AND quantity_remaining > 0
            """,
            (product_id,),
        ).fetchone()["quantity"]
        if remaining_stock > 0:
            flash(
                "This product cannot be archived while stock remains. Record a sale, documented correction, or disposal first.",
                "warning",
            )
            return redirect(url_for("products"))

        try:
            connection.execute(
                """
                UPDATE products
                SET is_archived = 1,
                    updated_at_utc = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                WHERE id = ? AND is_archived = 0
                """,
                (product_id,),
            )
            connection.commit()
        except sqlite3.IntegrityError:
            connection.rollback()
            flash(
                "The database rejected the archive because the product may still have stock. Refresh the catalogue and try again.",
                "warning",
            )
            return redirect(url_for("products"))

        flash("Product archived. Historical records have been preserved.", "success")
        return redirect(url_for("products"))


    @app.get("/batches")
    def batches():
        """Show batch-level stock, expiry risk, and remaining quantities."""
        if not Path(current_app.config["DATABASE"]).is_file():
            return render_template("setup.html", title="Initialize database"), 503

        query = request.args.get("q", "").strip()[:100]
        status = request.args.get("status", "all")
        if status not in {"all", "available", "near_expiry", "expired", "depleted"}:
            status = "all"

        try:
            connection = database.get_db()
            settings = connection.execute(
                "SELECT expiry_warning_days FROM app_settings WHERE id = 1"
            ).fetchone()
            warning_days = int(settings["expiry_warning_days"]) if settings else 7
            today = date.today()
            today_iso = today.isoformat()
            warning_end = (today + timedelta(days=warning_days)).isoformat()

            conditions: list[str] = []
            params: list[Any] = []
            if query:
                pattern = f"%{query}%"
                conditions.append(
                    "(p.name LIKE ? COLLATE NOCASE OR COALESCE(p.sku, '') LIKE ? COLLATE NOCASE "
                    "OR CAST(b.id AS TEXT) LIKE ?)"
                )
                params.extend([pattern, pattern, pattern])

            if status == "available":
                conditions.append(
                    "b.quantity_remaining > 0 AND (b.expiry_date IS NULL OR b.expiry_date > ?)"
                )
                params.append(warning_end)
            elif status == "near_expiry":
                conditions.append(
                    "b.quantity_remaining > 0 AND b.expiry_date IS NOT NULL "
                    "AND b.expiry_date >= ? AND b.expiry_date <= ?"
                )
                params.extend([today_iso, warning_end])
            elif status == "expired":
                conditions.append(
                    "b.quantity_remaining > 0 AND b.expiry_date IS NOT NULL AND b.expiry_date < ?"
                )
                params.append(today_iso)
            elif status == "depleted":
                conditions.append("b.quantity_remaining = 0")

            where_sql = " AND ".join(conditions) if conditions else "1 = 1"
            batches = connection.execute(
                f"""
                SELECT b.id AS batch_id, b.product_id, b.received_date, b.expiry_date,
                       b.quantity_received, b.quantity_remaining, b.unit_cost, b.created_at_utc,
                       p.name AS product_name, p.sku, p.unit, p.tracks_expiry, p.is_archived,
                       CASE
                           WHEN b.quantity_remaining = 0 THEN 'depleted'
                           WHEN b.expiry_date IS NOT NULL AND b.expiry_date < ? THEN 'expired'
                           WHEN b.expiry_date IS NOT NULL AND b.expiry_date <= ? THEN 'near_expiry'
                           ELSE 'available'
                       END AS batch_status
                FROM stock_batches AS b
                JOIN products AS p ON p.id = b.product_id
                WHERE {where_sql}
                ORDER BY
                    CASE
                        WHEN b.quantity_remaining = 0 THEN 3
                        WHEN b.expiry_date IS NOT NULL AND b.expiry_date < ? THEN 0
                        WHEN b.expiry_date IS NOT NULL AND b.expiry_date <= ? THEN 1
                        ELSE 2
                    END,
                    b.expiry_date ASC, b.received_date DESC, b.id DESC
                LIMIT 300
                """,
                [today_iso, warning_end, *params, today_iso, warning_end],
            ).fetchall()
            summary_row = connection.execute(
                """
                SELECT COUNT(*) AS total_batches,
                       COALESCE(SUM(CASE WHEN quantity_remaining > 0 THEN 1 ELSE 0 END), 0) AS active_batches,
                       COALESCE(SUM(CASE WHEN quantity_remaining > 0 AND expiry_date IS NOT NULL
                           AND expiry_date >= ? AND expiry_date <= ? THEN 1 ELSE 0 END), 0) AS near_expiry_batches,
                       COALESCE(SUM(CASE WHEN quantity_remaining > 0 AND expiry_date IS NOT NULL
                           AND expiry_date < ? THEN 1 ELSE 0 END), 0) AS expired_batches,
                       COALESCE(SUM(CASE WHEN quantity_remaining = 0 THEN 1 ELSE 0 END), 0) AS depleted_batches
                FROM stock_batches
                """,
                (today_iso, warning_end, today_iso),
            ).fetchone()
            summary = dict(summary_row)
            summary["expiry_warning_days"] = warning_days
        except (sqlite3.Error, FileNotFoundError):
            current_app.logger.exception("Unable to load stock batches.")
            return render_template(
                "error.html", title="Stock batches unavailable", error_code=503,
                message="Stock batches could not be loaded. Check the local database setup and try again.",
            ), 503

        return render_template(
            "batches/index.html", title="Stock batches", batches=batches, summary=summary,
            search_query=query, status=status, today=today_iso, warning_end=warning_end,
        )

    @app.route("/batches/new", methods=["GET", "POST"])
    def new_batch():
        """Receive stock into a new batch using the immutable movement ledger."""
        if not Path(current_app.config["DATABASE"]).is_file():
            return render_template("setup.html", title="Initialize database"), 503

        connection = database.get_db()
        products = connection.execute(
            """
            SELECT id, name, sku, unit, cost_price, tracks_expiry
            FROM products WHERE is_archived = 0 ORDER BY name COLLATE NOCASE
            """
        ).fetchall()
        today = date.today()
        defaults = {
            "product_id": "", "received_date": today.isoformat(), "expiry_date": "",
            "quantity_received": "", "unit_cost": "", "note": "",
        }
        form_data = dict(defaults)
        if request.method == "POST":
            for field in form_data:
                form_data[field] = str(request.form.get(field, "")).strip()

        if request.method == "GET":
            return render_template(
                "batches/form.html", title="Receive stock", form_data=form_data,
                errors={}, products=products, today=today.isoformat(),
            )
        if not _csrf_is_valid():
            abort(400)

        errors: dict[str, str] = {}
        max_integer = 9_223_372_036_854_775_807
        product = None
        if not re.fullmatch(r"[0-9]{1,19}", form_data["product_id"]):
            errors["product_id"] = "Choose an active product."
        else:
            chosen_id = int(form_data["product_id"])
            if chosen_id > max_integer:
                errors["product_id"] = "Choose an active product."
            else:
                product = connection.execute(
                    """
                    SELECT id, name, unit, cost_price, tracks_expiry
                    FROM products WHERE id = ? AND is_archived = 0
                    """,
                    (chosen_id,),
                ).fetchone()
                if product is None:
                    errors["product_id"] = (
                        "Choose an active product. Archived or missing products cannot receive stock."
                    )

        received_date = None
        try:
            received_date = date.fromisoformat(form_data["received_date"])
            if received_date.isoformat() != form_data["received_date"] or received_date > today:
                raise ValueError
        except (TypeError, ValueError):
            errors["received_date"] = "Enter a valid received date that is not in the future."

        expiry_date = None
        if form_data["expiry_date"]:
            try:
                expiry_date = date.fromisoformat(form_data["expiry_date"])
                if expiry_date.isoformat() != form_data["expiry_date"]:
                    raise ValueError
            except (TypeError, ValueError):
                errors["expiry_date"] = "Enter a valid expiry date."

        quantity = None
        if not re.fullmatch(r"[0-9]{1,19}", form_data["quantity_received"]):
            errors["quantity_received"] = "Quantity must be a whole number greater than zero."
        else:
            quantity = int(form_data["quantity_received"])
            if quantity < 1 or quantity > max_integer:
                errors["quantity_received"] = "Quantity must be a whole number greater than zero."

        unit_cost = None
        if not re.fullmatch(r"[0-9]{1,19}", form_data["unit_cost"]):
            errors["unit_cost"] = "Unit cost must be a whole number of zero or more."
        else:
            unit_cost = int(form_data["unit_cost"])
            if unit_cost > max_integer:
                errors["unit_cost"] = "Unit cost must be a whole number of zero or more."

        if len(form_data["note"]) > 500:
            errors["note"] = "Use no more than 500 characters for the note."
        if product is not None:
            if int(product["tracks_expiry"]) == 1 and expiry_date is None:
                errors["expiry_date"] = "An expiry date is required for this product."
            elif int(product["tracks_expiry"]) == 0 and expiry_date is not None:
                errors["expiry_date"] = "This product does not track expiry dates. Leave this field blank."
        if expiry_date is not None and received_date is not None and expiry_date < received_date:
            errors["expiry_date"] = "Expiry date cannot be earlier than the received date."

        if errors:
            return render_template(
                "batches/form.html", title="Receive stock", form_data=form_data,
                errors=errors, products=products, today=today.isoformat(),
            ), 400

        try:
            cursor = connection.execute(
                """
                INSERT INTO stock_operations (operation_type, request_token, business_date, note)
                VALUES ('receipt', ?, ?, ?)
                """,
                (secrets.token_urlsafe(32), received_date.isoformat(), form_data["note"] or None),
            )
            operation_id = cursor.lastrowid
            cursor = connection.execute(
                """
                INSERT INTO stock_batches (
                    product_id, receipt_operation_id, received_date, expiry_date,
                    quantity_received, quantity_remaining, unit_cost
                )
                VALUES (?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    int(product["id"]), operation_id, received_date.isoformat(),
                    expiry_date.isoformat() if expiry_date else None, quantity, unit_cost,
                ),
            )
            batch_id = cursor.lastrowid
            connection.execute(
                """
                INSERT INTO stock_movements (operation_id, product_id, batch_id, quantity_delta)
                VALUES (?, ?, ?, ?)
                """,
                (operation_id, int(product["id"]), batch_id, quantity),
            )
            connection.commit()
        except sqlite3.IntegrityError:
            connection.rollback()
            current_app.logger.exception("Stock receipt was rejected by the database.")
            errors["_form"] = (
                "The receipt could not be saved because it did not satisfy an inventory rule. "
                "Review the details and try again."
            )
            return render_template(
                "batches/form.html", title="Receive stock", form_data=form_data,
                errors=errors, products=products, today=today.isoformat(),
            ), 400
        except sqlite3.Error:
            connection.rollback()
            current_app.logger.exception("Unable to save stock receipt.")
            return render_template(
                "error.html", title="Stock receipt unavailable", error_code=503,
                message="The stock receipt could not be saved. No stock change was committed; try again.",
            ), 503

        flash(
            f"Stock received: {quantity} {product['unit']} of {product['name']} recorded in batch #{batch_id}.",
            "success",
        )
        return redirect(url_for("batches"))


    @app.get("/recommendations")
    def recommendations():
        """Estimate restock quantities from recent sales and sellable stock."""
        if not Path(current_app.config["DATABASE"]).is_file():
            return render_template("setup.html", title="Initialize database"), 503

        today = date.today()
        today_iso = today.isoformat()
        lookback_days = 30
        minimum_history_days = 7
        period_start = (today - timedelta(days=lookback_days - 1)).isoformat()
        search_query = request.args.get("q", "").strip()[:100]

        conditions = ["p.is_archived = 0"]
        params: list[Any] = [
            today_iso, today_iso, period_start, today_iso, today_iso,
        ]
        if search_query:
            conditions.append(
                "(p.name LIKE ? COLLATE NOCASE "
                "OR COALESCE(p.sku, '') LIKE ? COLLATE NOCASE)"
            )
            wildcard_query = f"%{search_query}%"
            params.extend([wildcard_query, wildcard_query])

        where_sql = " AND ".join(conditions)

        try:
            connection = database.get_db()
            rows = connection.execute(
                f"""
                WITH current_stock AS (
                    SELECT
                        product_id,
                        SUM(
                            CASE
                                WHEN quantity_remaining > 0
                                     AND received_date <= ?
                                     AND (expiry_date IS NULL OR expiry_date >= ?)
                                THEN quantity_remaining
                                ELSE 0
                            END
                        ) AS sellable_stock
                    FROM stock_batches
                    GROUP BY product_id
                ),
                sales_window AS (
                    SELECT
                        si.product_id,
                        SUM(si.quantity) AS units_sold,
                        MIN(op.business_date) AS first_sale_in_window
                    FROM sale_items AS si
                    JOIN sales AS s ON s.id = si.sale_id
                    JOIN stock_operations AS op ON op.id = s.operation_id
                    WHERE op.operation_type = 'sale'
                      AND op.business_date >= ?
                      AND op.business_date <= ?
                    GROUP BY si.product_id
                ),
                sales_history AS (
                    SELECT
                        si.product_id,
                        MIN(op.business_date) AS first_sale_ever
                    FROM sale_items AS si
                    JOIN sales AS s ON s.id = si.sale_id
                    JOIN stock_operations AS op ON op.id = s.operation_id
                    WHERE op.operation_type = 'sale'
                      AND op.business_date <= ?
                    GROUP BY si.product_id
                )
                SELECT
                    p.id,
                    p.name,
                    p.sku,
                    p.category,
                    p.unit,
                    p.lead_time_days,
                    p.safety_stock,
                    COALESCE(cs.sellable_stock, 0) AS sellable_stock,
                    COALESCE(sw.units_sold, 0) AS units_sold,
                    sw.first_sale_in_window,
                    sh.first_sale_ever
                FROM products AS p
                LEFT JOIN current_stock AS cs ON cs.product_id = p.id
                LEFT JOIN sales_window AS sw ON sw.product_id = p.id
                LEFT JOIN sales_history AS sh ON sh.product_id = p.id
                WHERE {where_sql}
                ORDER BY p.name COLLATE NOCASE ASC
                LIMIT 250
                """,
                params,
            ).fetchall()
        except (sqlite3.Error, FileNotFoundError):
            current_app.logger.exception("Unable to calculate restock recommendations.")
            return render_template(
                "error.html",
                title="Restock recommendations unavailable",
                error_code=503,
                message=(
                    "Restock recommendations could not be calculated. Check the database "
                    "setup and try again. No inventory records were changed."
                ),
            ), 503

        product_recommendations: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["sellable_stock"] = int(item["sellable_stock"] or 0)
            item["units_sold"] = int(item["units_sold"] or 0)
            item["lead_time_days"] = int(item["lead_time_days"])
            item["safety_stock"] = int(item["safety_stock"])
            item["recommendation_ready"] = False
            item["average_daily_sales"] = None
            item["target_stock"] = None
            item["suggested_restock"] = None
            item["history_days"] = 0

            first_sale_in_window = item["first_sale_in_window"]
            if not first_sale_in_window:
                if item["first_sale_ever"]:
                    item["status"] = "no_recent_sales"
                    item["status_label"] = "No recent sales"
                    item["explanation"] = (
                        "No sales were recorded in the last 30 days. "
                        "A quantity estimate is withheld to avoid an unsupported recommendation."
                    )
                else:
                    item["status"] = "no_history"
                    item["status_label"] = "No sales history"
                    item["explanation"] = (
                        "Record sales before using a sales-based restock estimate."
                    )
                product_recommendations.append(item)
                continue

            first_sale_date = date.fromisoformat(first_sale_in_window)
            item["history_days"] = min(
                lookback_days,
                max(1, (today - first_sale_date).days + 1),
            )

            if item["history_days"] < minimum_history_days:
                item["status"] = "building_history"
                item["status_label"] = "Building history"
                item["average_daily_sales"] = item["units_sold"] / item["history_days"]
                item["explanation"] = (
                    f"Only {item['history_days']} calendar day(s) of recorded sales are available. "
                    f"At least {minimum_history_days} days are required for a recommendation."
                )
                product_recommendations.append(item)
                continue

            average_daily_sales = item["units_sold"] / item["history_days"]
            target_stock = math.ceil(
                average_daily_sales * item["lead_time_days"] + item["safety_stock"]
            )
            suggested_restock = max(0, target_stock - item["sellable_stock"])

            item["status"] = "restock" if suggested_restock > 0 else "sufficient"
            item["status_label"] = (
                "Restock suggested" if suggested_restock > 0 else "Stock is sufficient"
            )
            item["recommendation_ready"] = True
            item["average_daily_sales"] = average_daily_sales
            item["target_stock"] = target_stock
            item["suggested_restock"] = suggested_restock
            item["explanation"] = (
                "Calculated from the observed sales period, product lead time, "
                "safety stock, and current sellable inventory."
            )
            product_recommendations.append(item)

        summary = {
            "active_products": len(product_recommendations),
            "restock_products": sum(
                item["status"] == "restock" for item in product_recommendations
            ),
            "suggested_units": sum(
                item["suggested_restock"] or 0 for item in product_recommendations
                if item["recommendation_ready"]
            ),
            "needs_more_data": sum(
                item["status"] in {"no_history", "no_recent_sales", "building_history"}
                for item in product_recommendations
            ),
        }

        return render_template(
            "recommendations/index.html",
            title="Restock recommendations",
            recommendations=product_recommendations,
            summary=summary,
            search_query=search_query,
            period_start=period_start,
            period_end=today_iso,
            lookback_days=lookback_days,
            minimum_history_days=minimum_history_days,
        )

    @app.get("/movements")
    def movements():
        """Show an append-only view of inventory changes."""
        if not Path(current_app.config["DATABASE"]).is_file():
            return render_template("setup.html", title="Initialize database"), 503

        query = request.args.get("q", "").strip()[:100]
        operation_type = request.args.get("type", "all")
        valid_types = {"all", "receipt", "sale", "disposal", "adjustment_in", "adjustment_out"}
        if operation_type not in valid_types:
            operation_type = "all"
        conditions: list[str] = []
        params: list[Any] = []
        if query:
            pattern = f"%{query}%"
            conditions.append(
                "(p.name LIKE ? COLLATE NOCASE OR COALESCE(p.sku, '') LIKE ? COLLATE NOCASE "
                "OR CAST(b.id AS TEXT) LIKE ?)"
            )
            params.extend([pattern, pattern, pattern])
        if operation_type != "all":
            conditions.append("op.operation_type = ?")
            params.append(operation_type)
        where_sql = " AND ".join(conditions) if conditions else "1 = 1"

        try:
            connection = database.get_db()
            rows = connection.execute(
                f"""
                SELECT sm.id AS movement_id, sm.quantity_delta, op.operation_type,
                       op.occurred_at_utc, op.business_date, op.reason, op.note,
                       p.name AS product_name, p.sku, p.unit, b.id AS batch_id, b.expiry_date
                FROM stock_movements AS sm
                JOIN stock_operations AS op ON op.id = sm.operation_id
                JOIN products AS p ON p.id = sm.product_id
                JOIN stock_batches AS b ON b.id = sm.batch_id
                WHERE {where_sql}
                ORDER BY op.occurred_at_utc DESC, sm.id DESC
                LIMIT 300
                """,
                params,
            ).fetchall()
        except (sqlite3.Error, FileNotFoundError):
            current_app.logger.exception("Unable to load stock movements.")
            return render_template(
                "error.html", title="Stock movements unavailable", error_code=503,
                message="The stock movement ledger could not be loaded. Check the local database setup and try again.",
            ), 503

        labels = {
            "receipt": "Stock received", "sale": "Sale", "disposal": "Disposal",
            "adjustment_in": "Stock adjustment · inbound",
            "adjustment_out": "Stock adjustment · outbound",
        }
        movement_rows = []
        for row in rows:
            item = dict(row)
            item["operation_label"] = labels.get(item["operation_type"], "Stock movement")
            delta = int(item["quantity_delta"])
            item["quantity_display"] = f"+{delta}" if delta > 0 else str(delta)
            movement_rows.append(item)

        return render_template(
            "movements/index.html", title="Stock movements", movements=movement_rows,
            search_query=query, operation_type=operation_type,
        )


    @app.get("/sales")
    def sales():
        """List recorded sales and their captured selling prices."""
        if not Path(current_app.config["DATABASE"]).is_file():
            return render_template("setup.html", title="Initialize database"), 503

        query = request.args.get("q", "").strip()[:100]
        conditions: list[str] = []
        params: list[Any] = []
        if query:
            pattern = f"%{query}%"
            conditions.append(
                "(p.name LIKE ? COLLATE NOCASE OR COALESCE(p.sku, '') LIKE ? COLLATE NOCASE "
                "OR CAST(s.id AS TEXT) LIKE ?)"
            )
            params.extend([pattern, pattern, pattern])
        where_sql = " AND ".join(conditions) if conditions else "1 = 1"

        try:
            connection = database.get_db()
            rows = connection.execute(
                f"""
                SELECT s.id AS sale_id, op.business_date, op.occurred_at_utc,
                       op.note, p.name AS product_name, p.sku, p.unit,
                       si.quantity, si.unit_selling_price,
                       si.quantity * si.unit_selling_price AS line_total
                FROM sales AS s
                JOIN stock_operations AS op ON op.id = s.operation_id
                JOIN sale_items AS si ON si.sale_id = s.id
                JOIN products AS p ON p.id = si.product_id
                WHERE {where_sql}
                ORDER BY op.occurred_at_utc DESC, s.id DESC
                LIMIT 250
                """,
                params,
            ).fetchall()
            summary = connection.execute(
                """
                SELECT
                    COUNT(DISTINCT s.id) AS transaction_count,
                    COALESCE(SUM(si.quantity * si.unit_selling_price), 0) AS gross_revenue,
                    COALESCE(SUM(CASE WHEN op.business_date = ? THEN 1 ELSE 0 END), 0) AS today_count,
                    COALESCE(SUM(CASE WHEN op.business_date = ?
                        THEN si.quantity * si.unit_selling_price ELSE 0 END), 0) AS today_revenue
                FROM sales AS s
                JOIN stock_operations AS op ON op.id = s.operation_id
                JOIN sale_items AS si ON si.sale_id = s.id
                """,
                (date.today().isoformat(), date.today().isoformat()),
            ).fetchone()
        except (sqlite3.Error, FileNotFoundError):
            current_app.logger.exception("Unable to load sales history.")
            return render_template(
                "error.html", title="Sales history unavailable", error_code=503,
                message="Sales history could not be loaded. Check the local database setup and try again.",
            ), 503

        return render_template(
            "sales/index.html", title="Sales history", sales=rows,
            summary=dict(summary), search_query=query,
        )

    @app.route("/sales/new", methods=["GET", "POST"])
    def new_sale():
        """Record one product sale and allocate stock using FEFO."""
        if not Path(current_app.config["DATABASE"]).is_file():
            return render_template("setup.html", title="Initialize database"), 503

        connection = database.get_db()
        today = date.today()
        products = connection.execute(
            """
            SELECT p.id, p.name, p.sku, p.unit, p.selling_price, p.tracks_expiry,
                   COALESCE((
                       SELECT SUM(b.quantity_remaining)
                       FROM stock_batches AS b
                       WHERE b.product_id = p.id AND b.quantity_remaining > 0
                         AND (b.expiry_date IS NULL OR b.expiry_date >= ?)
                   ), 0) AS available_quantity
            FROM products AS p
            WHERE p.is_archived = 0
            ORDER BY p.name COLLATE NOCASE
            """,
            (today.isoformat(),),
        ).fetchall()
        form_data = {
            "product_id": "", "business_date": today.isoformat(),
            "quantity": "", "note": "",
        }
        if request.method == "POST":
            for field in form_data:
                form_data[field] = str(request.form.get(field, "")).strip()
        if request.method == "GET":
            return render_template(
                "sales/form.html", title="Record a sale", products=products,
                form_data=form_data, errors={}, today=today.isoformat(),
            )
        if not _csrf_is_valid():
            abort(400)

        errors: dict[str, str] = {}
        max_integer = 9_223_372_036_854_775_807
        product = None
        product_raw = form_data["product_id"]
        if not re.fullmatch(r"[0-9]{1,19}", product_raw):
            errors["product_id"] = "Choose an active product."
        else:
            product_id = int(product_raw)
            if product_id > max_integer:
                errors["product_id"] = "Choose an active product."
            else:
                product = connection.execute(
                    """
                    SELECT id, name, unit, selling_price
                    FROM products WHERE id = ? AND is_archived = 0
                    """,
                    (product_id,),
                ).fetchone()
                if product is None:
                    errors["product_id"] = "Choose an active product. Archived products cannot be sold."

        business_date = None
        try:
            business_date = date.fromisoformat(form_data["business_date"])
            if business_date.isoformat() != form_data["business_date"] or business_date > today:
                raise ValueError
        except (TypeError, ValueError):
            errors["business_date"] = "Enter a valid business date that is not in the future."

        quantity = None
        if not re.fullmatch(r"[0-9]{1,19}", form_data["quantity"]):
            errors["quantity"] = "Quantity must be a whole number greater than zero."
        else:
            quantity = int(form_data["quantity"])
            if quantity < 1 or quantity > max_integer:
                errors["quantity"] = "Quantity must be a whole number greater than zero."

        if len(form_data["note"]) > 500:
            errors["note"] = "Use no more than 500 characters for the note."

        allocations: list[tuple[int, int]] = []
        if product is not None and business_date is not None and quantity is not None and quantity > 0:
            batches = connection.execute(
                """
                SELECT id, quantity_remaining
                FROM stock_batches
                WHERE product_id = ?
                  AND quantity_remaining > 0
                  AND received_date <= ?
                  AND (expiry_date IS NULL OR expiry_date >= ?)
                ORDER BY
                    CASE WHEN expiry_date IS NULL THEN 1 ELSE 0 END,
                    expiry_date ASC, received_date ASC, id ASC
                """,
                (int(product["id"]), business_date.isoformat(), business_date.isoformat()),
            ).fetchall()
            available = sum(int(batch["quantity_remaining"]) for batch in batches)
            if quantity > available:
                errors["_form"] = (
                    f"Not enough sellable stock for this date. "
                    f"Available quantity: {available} {product['unit']}."
                )
            else:
                quantity_left = quantity
                for batch in batches:
                    allocation = min(quantity_left, int(batch["quantity_remaining"]))
                    if allocation > 0:
                        allocations.append((int(batch["id"]), allocation))
                        quantity_left -= allocation
                    if quantity_left == 0:
                        break

        if errors:
            return render_template(
                "sales/form.html", title="Record a sale", products=products,
                form_data=form_data, errors=errors, today=today.isoformat(),
            ), 400

        try:
            cursor = connection.execute(
                """
                INSERT INTO stock_operations (operation_type, request_token, business_date, note)
                VALUES ('sale', ?, ?, ?)
                """,
                (
                    secrets.token_urlsafe(32), business_date.isoformat(),
                    form_data["note"] or None,
                ),
            )
            operation_id = cursor.lastrowid
            cursor = connection.execute(
                "INSERT INTO sales (operation_id) VALUES (?)",
                (operation_id,),
            )
            sale_id = cursor.lastrowid
            cursor = connection.execute(
                """
                INSERT INTO sale_items (sale_id, product_id, quantity, unit_selling_price)
                VALUES (?, ?, ?, ?)
                """,
                (sale_id, int(product["id"]), quantity, int(product["selling_price"])),
            )
            sale_item_id = cursor.lastrowid
            for batch_id, allocated_quantity in allocations:
                connection.execute(
                    """
                    INSERT INTO stock_movements (
                        operation_id, product_id, batch_id, sale_item_id, quantity_delta
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        operation_id, int(product["id"]), batch_id,
                        sale_item_id, -allocated_quantity,
                    ),
                )
            connection.commit()
        except sqlite3.IntegrityError:
            connection.rollback()
            current_app.logger.exception("Sale was rejected by the database.")
            errors["_form"] = (
                "The sale could not be saved because an inventory rule was not satisfied. "
                "No stock was changed; review the details and try again."
            )
            return render_template(
                "sales/form.html", title="Record a sale", products=products,
                form_data=form_data, errors=errors, today=today.isoformat(),
            ), 400
        except sqlite3.Error:
            connection.rollback()
            current_app.logger.exception("Unable to save sale.")
            return render_template(
                "error.html", title="Sale could not be saved", error_code=503,
                message="The sale could not be saved. No stock change was committed; try again.",
            ), 503

        total = int(quantity) * int(product["selling_price"])
        flash(
            f"Sale #{sale_id} recorded: {quantity} {product['unit']} of {product['name']} for Rp {total:,}.",
            "success",
        )
        return redirect(url_for("sales"))

    @app.get("/health")
    def health():
        """Return a small local readiness check without exposing database details."""
        database_path = Path(current_app.config["DATABASE"])

        if not database_path.is_file():
            return jsonify({"status": "setup_required"}), 503

        try:
            connection = database.get_db()
            connection.execute("SELECT 1").fetchone()
            foreign_keys_enabled = connection.execute(
                "PRAGMA foreign_keys"
            ).fetchone()[0] == 1
        except (sqlite3.Error, FileNotFoundError):
            current_app.logger.exception("WarungWise health check failed.")
            return jsonify({"status": "database_error"}), 503

        if not foreign_keys_enabled:
            return jsonify({"status": "foreign_keys_disabled"}), 503

        return jsonify({"status": "ok"}), 200

    @app.errorhandler(400)
    def bad_request(_error):
        return render_template(
            "error.html",
            title="Invalid request",
            error_code=400,
            message="The request could not be verified. Refresh the page and try again.",
        ), 400

    @app.errorhandler(404)
    def not_found(_error):
        return render_template(
            "error.html",
            title="Page not found",
            error_code=404,
            message="The page you requested does not exist.",
        ), 404

    @app.errorhandler(500)
    def internal_error(_error):
        current_app.logger.error("An unhandled application error occurred.")
        return render_template(
            "error.html",
            title="Unexpected error",
            error_code=500,
            message="An unexpected error occurred. Please try again.",
        ), 500

    if not app.testing:
        app.logger.setLevel(logging.INFO)

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(
        host="127.0.0.1",
        port=5000,
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
