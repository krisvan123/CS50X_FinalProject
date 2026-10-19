"""WarungWise Flask application entry point and product-management workflows."""
from __future__ import annotations

import hmac
import logging
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
    return isinstance(expected, str) and bool(supplied) and hmac.compare_digest(expected, supplied)


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

    numeric_fields = ("cost_price", "selling_price", "minimum_stock", "lead_time_days", "safety_stock")
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
        value = int(raw_value)
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



def _load_dashboard_data(connection: sqlite3.Connection) -> tuple[dict[str, Any], list[dict[str, Any]]]:
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

    return stats, recent_movements


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
            stats, recent_movements = _load_dashboard_data(connection)
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
