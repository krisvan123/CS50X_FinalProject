"""WarungWise Flask application entry point and product-management workflows."""

# AI-use disclosure: ChatGPT assisted with planning, drafting, and refining selected
# routes, validation, reporting, and tests. The project author should review and
# understand these sections before submission.
from __future__ import annotations

import csv
import hmac
import logging
import math
import os
import re
import secrets
from io import StringIO
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from flask import (
    Flask, Response, abort, current_app, flash, jsonify, redirect, render_template,
    request, session, url_for,
)

import database




PRODUCT_TEXT_LIMITS = {"name": 120, "sku": 50, "category": 80, "unit": 30}


REPORT_MAX_DAYS = 366
REPORT_DEFAULT_DAYS = 30


def _parse_report_period(
    start_value: str,
    end_value: str,
    today: date,
) -> tuple[date, date, str | None]:
    """Validate a report date range without accepting ambiguous date formats."""
    default_start = today - timedelta(days=REPORT_DEFAULT_DAYS - 1)

    try:
        start_date = date.fromisoformat(start_value) if start_value else default_start
        end_date = date.fromisoformat(end_value) if end_value else today
    except ValueError:
        return default_start, today, "Enter valid start and end dates."

    if (start_value and start_date.isoformat() != start_value) or (
        end_value and end_date.isoformat() != end_value
    ):
        return default_start, today, "Dates must use the YYYY-MM-DD format."
    if start_date > today or end_date > today:
        return default_start, today, "Report dates cannot be in the future."
    if start_date > end_date:
        return default_start, today, "The start date must be on or before the end date."
    if (end_date - start_date).days >= REPORT_MAX_DAYS:
        return default_start, today, f"Choose a date range of no more than {REPORT_MAX_DAYS} days."

    return start_date, end_date, None


def _fetch_report_sales_rows(
    connection: sqlite3.Connection,
    start_date: str,
    end_date: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Read sale-line records for a reporting period; no stock is modified."""
    sql = """
        SELECT s.id AS sale_id, op.business_date, op.occurred_at_utc,
               op.note, p.name AS product_name, p.sku, p.unit,
               si.quantity, si.unit_selling_price,
               si.quantity * si.unit_selling_price AS gross_total
        FROM sales AS s
        JOIN stock_operations AS op ON op.id = s.operation_id
        JOIN sale_items AS si ON si.sale_id = s.id
        JOIN products AS p ON p.id = si.product_id
        WHERE op.operation_type = 'sale'
          AND op.business_date >= ? AND op.business_date <= ?
        ORDER BY op.business_date DESC, op.occurred_at_utc DESC, s.id DESC
    """
    params: list[Any] = [start_date, end_date]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(row) for row in connection.execute(sql, params).fetchall()]


def _fetch_report_movement_rows(
    connection: sqlite3.Connection,
    start_date: str,
    end_date: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Read stock movement audit records over a selected business-date period."""
    sql = """
        SELECT sm.id AS movement_id, sm.quantity_delta, op.operation_type,
               op.occurred_at_utc, op.business_date, op.reason, op.note,
               p.name AS product_name, p.sku, p.unit,
               b.id AS batch_id, b.expiry_date
        FROM stock_movements AS sm
        JOIN stock_operations AS op ON op.id = sm.operation_id
        JOIN products AS p ON p.id = sm.product_id
        JOIN stock_batches AS b ON b.id = sm.batch_id
        WHERE op.business_date >= ? AND op.business_date <= ?
        ORDER BY op.business_date DESC, op.occurred_at_utc DESC, sm.id DESC
    """
    params: list[Any] = [start_date, end_date]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(row) for row in connection.execute(sql, params).fetchall()]


def _fetch_inventory_snapshot(
    connection: sqlite3.Connection,
    today: date,
    warning_days: int,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Read current non-depleted batches and calculate their display status."""
    sql = """
        SELECT b.id AS batch_id, b.received_date, b.expiry_date,
               b.quantity_received, b.quantity_remaining, b.unit_cost,
               p.id AS product_id, p.name AS product_name, p.sku,
               p.category, p.unit, p.minimum_stock
        FROM stock_batches AS b
        JOIN products AS p ON p.id = b.product_id
        WHERE b.quantity_remaining > 0
        ORDER BY
            CASE WHEN b.expiry_date IS NULL THEN 1 ELSE 0 END,
            b.expiry_date ASC, p.name COLLATE NOCASE ASC, b.id ASC
    """
    params: list[Any] = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    rows = connection.execute(sql, params).fetchall()
    warning_end = today + timedelta(days=warning_days)
    snapshot: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        expiry_value = item["expiry_date"]
        if not expiry_value:
            item["batch_status"] = "No expiry date"
        else:
            expiry_date = date.fromisoformat(expiry_value)
            if expiry_date < today:
                item["batch_status"] = "Expired"
            elif expiry_date <= warning_end:
                item["batch_status"] = "Near expiry"
            else:
                item["batch_status"] = "Available"
        snapshot.append(item)
    return snapshot


def _historical_sellable_capacity(
    connection: sqlite3.Connection,
    batch_id: int,
    business_date: str,
) -> int:
    """Return the maximum safe backdated issue quantity for a batch.

    A backdated sale must be supported on its business date and after each
    subsequent movement. Current stock alone can conceal an intermediate
    negative historical balance that later stock actions repaired.
    """
    movement_rows = connection.execute(
        """
        SELECT op.business_date, op.occurred_at_utc, sm.id, sm.quantity_delta
        FROM stock_movements AS sm
        JOIN stock_operations AS op ON op.id = sm.operation_id
        WHERE sm.batch_id = ?
        ORDER BY op.business_date ASC, op.occurred_at_utc ASC, sm.id ASC
        """,
        (batch_id,),
    ).fetchall()

    running_balance = 0
    balance_on_sale_date = None
    minimum_future_balance = None
    for movement in movement_rows:
        running_balance += int(movement["quantity_delta"])
        if movement["business_date"] <= business_date:
            balance_on_sale_date = running_balance
        elif balance_on_sale_date is not None:
            if minimum_future_balance is None:
                minimum_future_balance = running_balance
            else:
                minimum_future_balance = min(minimum_future_balance, running_balance)

    if balance_on_sale_date is None:
        return 0

    safe_quantity = balance_on_sale_date
    if minimum_future_balance is not None:
        safe_quantity = min(safe_quantity, minimum_future_balance)
    return max(0, int(safe_quantity))


def _safe_csv_text(value: Any) -> str:
    """Prevent untrusted text fields from being interpreted as spreadsheet formulas."""
    text_value = "" if value is None else str(value)
    if text_value.lstrip(" \t\r\n")[:1] in {"=", "+", "-", "@", "\t", "\r"}:
        return "'" + text_value
    return text_value



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


def _begin_inventory_write(connection: sqlite3.Connection) -> bool:
    """Acquire SQLite's write reservation before reading stock for a mutation.

    BEGIN IMMEDIATE serializes stock-changing requests before their duplicate
    token and balance checks. This avoids stale read-to-write upgrades when two
    requests arrive together; the unique request-token constraint remains the
    final duplicate-operation safeguard.
    """
    try:
        connection.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError:
        current_app.logger.warning(
            "Could not acquire SQLite write reservation for an inventory operation."
        )
        return False
    return True


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
        DATABASE=os.environ.get("WARUNGWISE_DATABASE") or str(Path(app.instance_path) / "warungwise.db"),
        DEMO_READ_ONLY=os.environ.get("WARUNGWISE_DEMO_READ_ONLY", "").strip().lower() in {"1", "true", "yes"},
        MAX_CONTENT_LENGTH=1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    if test_config is not None:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    database.init_app(app)

    @app.after_request
    def add_security_headers(response: Response) -> Response:
        """Apply conservative browser security and dynamic-page cache headers."""
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'self'; form-action 'self'; "
            "frame-ancestors 'none'; object-src 'none'; img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net data:; "
            "script-src 'self'; connect-src 'self'",
        )
        # Inventory pages contain business information; avoid storing dynamic pages
        # in browser or intermediary caches. Static assets remain cacheable.
        if request.endpoint != "static":
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.before_request
    def enforce_public_demo_read_only() -> Response | tuple[str, int] | None:
        """Prevent visitors from changing records in the public sample deployment."""
        if (
            current_app.config.get("DEMO_READ_ONLY", False)
            and request.method not in {"GET", "HEAD", "OPTIONS"}
        ):
            return render_template(
                "error.html",
                title="Public demo is read-only",
                error_code=403,
                message=(
                    "This public preview uses fictional sample data and does not accept "
                    "changes. Run the demo locally to try inventory workflows."
                ),
            ), 403
        return None

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
        request_token = secrets.token_urlsafe(32)
        if request.method == "POST":
            for field in form_data:
                form_data[field] = str(request.form.get(field, "")).strip()
            request_token = str(request.form.get("request_token", "")).strip()

        if request.method == "GET":
            return render_template(
                "batches/form.html", title="Receive stock", form_data=form_data,
                errors={}, products=products, today=today.isoformat(),
                request_token=request_token,
            )
        if not _csrf_is_valid():
            abort(400)
        if not re.fullmatch(r"[A-Za-z0-9_-]{40,128}", request_token):
            abort(400)

        if not _begin_inventory_write(connection):
            return render_template(
                "error.html", title="Inventory busy", error_code=503,
                message="Another inventory change is being saved. No stock change was made; wait a moment and retry.",
            ), 503

        existing_operation = connection.execute(
            "SELECT operation_type FROM stock_operations WHERE request_token = ?",
            (request_token,),
        ).fetchone()
        if existing_operation is not None:
            if existing_operation["operation_type"] == "receipt":
                flash("This stock receipt was already processed. No duplicate receipt was created.", "info")
                return redirect(url_for("batches"))
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
                request_token=request_token,
            ), 400

        try:
            cursor = connection.execute(
                """
                INSERT INTO stock_operations (operation_type, request_token, business_date, note)
                VALUES ('receipt', ?, ?, ?)
                """,
                (request_token, received_date.isoformat(), form_data["note"] or None),
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
            duplicate = connection.execute(
                "SELECT operation_type FROM stock_operations WHERE request_token = ?",
                (request_token,),
            ).fetchone()
            if duplicate is not None and duplicate["operation_type"] == "receipt":
                flash("This stock receipt was already processed. No duplicate receipt was created.", "info")
                return redirect(url_for("batches"))
            current_app.logger.exception("Stock receipt was rejected by the database.")
            errors["_form"] = (
                "The receipt could not be saved because it did not satisfy an inventory rule. "
                "Review the details and try again."
            )
            return render_template(
                "batches/form.html", title="Receive stock", form_data=form_data,
                errors=errors, products=products, today=today.isoformat(),
                request_token=request_token,
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



    @app.get("/reports")
    def reports():
        """Show date-filtered sales analysis and a current inventory snapshot."""
        if not Path(current_app.config["DATABASE"]).is_file():
            return render_template("setup.html", title="Initialize database"), 503

        today = date.today()
        start_date, end_date, period_error = _parse_report_period(
            request.args.get("start_date", "").strip(),
            request.args.get("end_date", "").strip(),
            today,
        )
        if period_error:
            return render_template(
                "error.html",
                title="Invalid report date range",
                error_code=400,
                message=period_error,
            ), 400

        start_iso = start_date.isoformat()
        end_iso = end_date.isoformat()
        try:
            connection = database.get_db()
            summary_row = connection.execute(
                """
                SELECT
                    COUNT(DISTINCT s.id) AS transaction_count,
                    COALESCE(SUM(si.quantity), 0) AS units_sold,
                    COALESCE(SUM(si.quantity * si.unit_selling_price), 0) AS gross_revenue
                FROM sales AS s
                JOIN stock_operations AS op ON op.id = s.operation_id
                JOIN sale_items AS si ON si.sale_id = s.id
                WHERE op.operation_type = 'sale'
                  AND op.business_date >= ? AND op.business_date <= ?
                """,
                (start_iso, end_iso),
            ).fetchone()
            daily_rows = connection.execute(
                """
                SELECT
                    op.business_date,
                    COUNT(DISTINCT s.id) AS transaction_count,
                    COALESCE(SUM(si.quantity), 0) AS units_sold,
                    COALESCE(SUM(si.quantity * si.unit_selling_price), 0) AS gross_revenue
                FROM sales AS s
                JOIN stock_operations AS op ON op.id = s.operation_id
                JOIN sale_items AS si ON si.sale_id = s.id
                WHERE op.operation_type = 'sale'
                  AND op.business_date >= ? AND op.business_date <= ?
                GROUP BY op.business_date
                ORDER BY op.business_date ASC
                """,
                (start_iso, end_iso),
            ).fetchall()
            top_products = connection.execute(
                """
                SELECT p.name AS product_name, p.sku, p.unit,
                       SUM(si.quantity) AS units_sold,
                       SUM(si.quantity * si.unit_selling_price) AS gross_revenue,
                       COUNT(DISTINCT s.id) AS transaction_count
                FROM sales AS s
                JOIN stock_operations AS op ON op.id = s.operation_id
                JOIN sale_items AS si ON si.sale_id = s.id
                JOIN products AS p ON p.id = si.product_id
                WHERE op.operation_type = 'sale'
                  AND op.business_date >= ? AND op.business_date <= ?
                GROUP BY p.id, p.name, p.sku, p.unit
                ORDER BY gross_revenue DESC, units_sold DESC, p.name COLLATE NOCASE ASC
                LIMIT 10
                """,
                (start_iso, end_iso),
            ).fetchall()
            movement_count = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM stock_movements AS sm
                JOIN stock_operations AS op ON op.id = sm.operation_id
                WHERE op.business_date >= ? AND op.business_date <= ?
                """,
                (start_iso, end_iso),
            ).fetchone()["total"]
            disposal_value = connection.execute(
                """
                SELECT COALESCE(SUM(ABS(sm.quantity_delta) * b.unit_cost), 0) AS total
                FROM stock_movements AS sm
                JOIN stock_operations AS op ON op.id = sm.operation_id
                JOIN stock_batches AS b ON b.id = sm.batch_id
                WHERE op.operation_type = 'disposal'
                  AND op.business_date >= ? AND op.business_date <= ?
                """,
                (start_iso, end_iso),
            ).fetchone()["total"]
            settings = connection.execute(
                "SELECT expiry_warning_days FROM app_settings WHERE id = 1"
            ).fetchone()
            warning_days = int(settings["expiry_warning_days"]) if settings else 7
            inventory_summary = connection.execute(
                """
                SELECT
                    COALESCE(SUM(CASE
                        WHEN b.quantity_remaining > 0
                         AND b.received_date <= ?
                         AND (b.expiry_date IS NULL OR b.expiry_date >= ?)
                        THEN b.quantity_remaining ELSE 0 END), 0) AS sellable_units,
                    SUM(CASE WHEN b.quantity_remaining > 0 THEN 1 ELSE 0 END) AS stocked_batches,
                    SUM(CASE WHEN b.quantity_remaining > 0 AND b.expiry_date < ?
                        THEN 1 ELSE 0 END) AS expired_batches,
                    SUM(CASE WHEN b.quantity_remaining > 0
                        AND b.expiry_date >= ? AND b.expiry_date <= ?
                        THEN 1 ELSE 0 END) AS near_expiry_batches
                FROM stock_batches AS b
                JOIN products AS p ON p.id = b.product_id
                WHERE p.is_archived = 0
                """,
                (
                    today.isoformat(), today.isoformat(), today.isoformat(),
                    today.isoformat(), (today + timedelta(days=warning_days)).isoformat(),
                ),
            ).fetchone()
            sales_rows = _fetch_report_sales_rows(connection, start_iso, end_iso, limit=20)
            movement_rows = _fetch_report_movement_rows(connection, start_iso, end_iso, limit=20)
            inventory_rows = _fetch_inventory_snapshot(connection, today, warning_days, limit=12)
        except (sqlite3.Error, FileNotFoundError, ValueError):
            current_app.logger.exception("Unable to load reports.")
            return render_template(
                "error.html",
                title="Reports unavailable",
                error_code=503,
                message="The reports could not be loaded. Check the database setup and try again.",
            ), 503

        daily_by_date = {row["business_date"]: dict(row) for row in daily_rows}
        peak_revenue = max(
            (int(row["gross_revenue"] or 0) for row in daily_rows),
            default=0,
        )
        daily_chart: list[dict[str, Any]] = []
        day = start_date
        while day <= end_date:
            key = day.isoformat()
            daily = daily_by_date.get(key, {})
            revenue = int(daily.get("gross_revenue", 0) or 0)
            daily_chart.append({
                "date": key,
                "day_label": day.strftime("%d"),
                "month_label": day.strftime("%d %b"),
                "gross_revenue": revenue,
                "transaction_count": int(daily.get("transaction_count", 0) or 0),
                "units_sold": int(daily.get("units_sold", 0) or 0),
                "height_percent": (
                    max(4, round(revenue * 100 / peak_revenue))
                    if peak_revenue and revenue else 0
                ),
                "show_label": (
                    day == start_date or day == end_date or day.day == 1
                    or (day - start_date).days % 5 == 0
                ),
            })
            day += timedelta(days=1)

        summary = dict(summary_row)
        summary["transaction_count"] = int(summary["transaction_count"] or 0)
        summary["units_sold"] = int(summary["units_sold"] or 0)
        summary["gross_revenue"] = int(summary["gross_revenue"] or 0)
        summary["recorded_disposal_value"] = int(disposal_value or 0)
        current_inventory = dict(inventory_summary)
        for key in ("sellable_units", "stocked_batches", "expired_batches", "near_expiry_batches"):
            current_inventory[key] = int(current_inventory[key] or 0)

        movement_labels = {
            "receipt": "Stock received",
            "sale": "Sale",
            "disposal": "Disposal",
            "adjustment_in": "Stock adjustment · inbound",
            "adjustment_out": "Stock adjustment · outbound",
        }
        for movement in movement_rows:
            movement["operation_label"] = movement_labels.get(
                movement["operation_type"], "Stock movement"
            )
            delta = int(movement["quantity_delta"])
            movement["quantity_display"] = f"+{delta}" if delta > 0 else str(delta)

        return render_template(
            "reports/index.html",
            title="Reports & analytics",
            summary=summary,
            top_products=[dict(row) for row in top_products],
            daily_chart=daily_chart,
            peak_revenue=peak_revenue,
            movements=movement_rows,
            sales=sales_rows,
            inventory=inventory_rows,
            current_inventory=current_inventory,
            warning_days=warning_days,
            start_date=start_iso,
            end_date=end_iso,
            today=today.isoformat(),
            movement_count=int(movement_count or 0),
        )

    @app.get("/reports/export/<report_type>")
    def export_report(report_type: str):
        """Export filtered sales, dated stock movements, or current batch stock to CSV."""
        if report_type not in {"sales", "movements", "inventory"}:
            abort(404)
        if not Path(current_app.config["DATABASE"]).is_file():
            return render_template("setup.html", title="Initialize database"), 503

        today = date.today()
        if report_type == "inventory":
            start_date = today
            end_date = today
        else:
            start_date, end_date, period_error = _parse_report_period(
                request.args.get("start_date", "").strip(),
                request.args.get("end_date", "").strip(),
                today,
            )
            if period_error:
                return Response(period_error + "\n", status=400, mimetype="text/plain")

        try:
            connection = database.get_db()
            if report_type == "sales":
                rows = _fetch_report_sales_rows(
                    connection, start_date.isoformat(), end_date.isoformat()
                )
                headers = [
                    "Sale ID", "Business Date", "Recorded At (UTC)", "Product", "SKU",
                    "Quantity", "Unit", "Unit Selling Price (IDR)", "Gross Total (IDR)", "Note",
                ]
                data = [
                    [
                        row["sale_id"], row["business_date"], row["occurred_at_utc"],
                        _safe_csv_text(row["product_name"]), _safe_csv_text(row["sku"]),
                        row["quantity"], _safe_csv_text(row["unit"]),
                        row["unit_selling_price"], row["gross_total"], _safe_csv_text(row["note"]),
                    ]
                    for row in rows
                ]
                filename = f"warungwise_sales_{start_date.isoformat()}_{end_date.isoformat()}.csv"
            elif report_type == "movements":
                rows = _fetch_report_movement_rows(
                    connection, start_date.isoformat(), end_date.isoformat()
                )
                headers = [
                    "Movement ID", "Business Date", "Recorded At (UTC)", "Operation Type",
                    "Product", "SKU", "Batch ID", "Quantity Delta", "Unit", "Expiry Date",
                    "Reason", "Note",
                ]
                data = [
                    [
                        row["movement_id"], row["business_date"], row["occurred_at_utc"],
                        _safe_csv_text(row["operation_type"]), _safe_csv_text(row["product_name"]),
                        _safe_csv_text(row["sku"]), row["batch_id"], row["quantity_delta"],
                        _safe_csv_text(row["unit"]), row["expiry_date"],
                        _safe_csv_text(row["reason"]), _safe_csv_text(row["note"]),
                    ]
                    for row in rows
                ]
                filename = f"warungwise_movements_{start_date.isoformat()}_{end_date.isoformat()}.csv"
            else:
                settings = connection.execute(
                    "SELECT expiry_warning_days FROM app_settings WHERE id = 1"
                ).fetchone()
                warning_days = int(settings["expiry_warning_days"]) if settings else 7
                rows = _fetch_inventory_snapshot(connection, today, warning_days)
                headers = [
                    "Batch ID", "Product", "SKU", "Category", "Received Date", "Expiry Date",
                    "Quantity Received", "Quantity Remaining", "Unit", "Unit Cost (IDR)", "Status",
                ]
                data = [
                    [
                        row["batch_id"], _safe_csv_text(row["product_name"]),
                        _safe_csv_text(row["sku"]), _safe_csv_text(row["category"]),
                        row["received_date"], row["expiry_date"], row["quantity_received"],
                        row["quantity_remaining"], _safe_csv_text(row["unit"]),
                        row["unit_cost"], _safe_csv_text(row["batch_status"]),
                    ]
                    for row in rows
                ]
                filename = f"warungwise_inventory_snapshot_{today.isoformat()}.csv"
        except (sqlite3.Error, FileNotFoundError, ValueError):
            current_app.logger.exception("Unable to export report CSV.")
            return render_template(
                "error.html",
                title="CSV export unavailable",
                error_code=503,
                message="The CSV file could not be generated. Check the database setup and try again.",
            ), 503

        output = StringIO(newline="")
        csv_writer = csv.writer(output)
        csv_writer.writerow(headers)
        csv_writer.writerows(data)
        response = Response("\ufeff" + output.getvalue(), mimetype="text/csv")
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.headers["Cache-Control"] = "no-store"
        return response

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


    @app.route("/stock-actions/new", methods=["GET", "POST"])
    def new_stock_action():
        """Record a disposal or justified stock-count correction against an existing batch."""
        if not Path(current_app.config["DATABASE"]).is_file():
            return render_template("setup.html", title="Initialize database"), 503

        connection = database.get_db()
        today = date.today()
        defaults = {
            "batch_id": "", "operation_type": "disposal",
            "business_date": today.isoformat(), "quantity": "",
            "reason": "", "note": "",
        }
        form_data = dict(defaults)
        request_token = secrets.token_urlsafe(32)
        if request.method == "POST":
            for field in form_data:
                form_data[field] = str(request.form.get(field, "")).strip()
            request_token = str(request.form.get("request_token", "")).strip()

        batches = connection.execute(
            """
            SELECT b.id AS batch_id, b.product_id, b.received_date, b.expiry_date,
                   b.quantity_remaining, b.unit_cost, p.name AS product_name,
                   p.sku, p.unit
            FROM stock_batches AS b
            JOIN products AS p ON p.id = b.product_id
            WHERE p.is_archived = 0
            ORDER BY p.name COLLATE NOCASE, b.received_date DESC, b.id DESC
            LIMIT 500
            """
        ).fetchall()

        if request.method == "GET":
            return render_template(
                "stock_actions/form.html", title="Waste & stock corrections",
                form_data=form_data, batches=batches, errors={},
                request_token=request_token, today=today.isoformat(),
            )
        if not _csrf_is_valid():
            abort(400)
        if not re.fullmatch(r"[A-Za-z0-9_-]{40,128}", request_token):
            abort(400)

        operation_type = form_data["operation_type"]
        if operation_type not in {"disposal", "adjustment_out", "adjustment_in"}:
            errors = {"operation_type": "Choose a supported stock action."}
            return render_template(
                "stock_actions/form.html", title="Waste & stock corrections",
                form_data=form_data, batches=batches, errors=errors,
                request_token=request_token, today=today.isoformat(),
            ), 400

        if not _begin_inventory_write(connection):
            return render_template(
                "error.html", title="Inventory busy", error_code=503,
                message="Another inventory change is being saved. No stock change was made; wait a moment and retry.",
            ), 503

        existing_operation = connection.execute(
            "SELECT operation_type FROM stock_operations WHERE request_token = ?",
            (request_token,),
        ).fetchone()
        if existing_operation is not None:
            if existing_operation["operation_type"] == operation_type:
                flash("This stock action was already processed. No duplicate movement was created.", "info")
                return redirect(url_for("movements"))
            abort(400)

        errors: dict[str, str] = {}
        max_integer = 9_223_372_036_854_775_807
        batch = None
        batch_raw = form_data["batch_id"]
        if not re.fullmatch(r"[0-9]{1,19}", batch_raw):
            errors["batch_id"] = "Choose an existing batch."
        else:
            chosen_batch_id = int(batch_raw)
            if chosen_batch_id > max_integer:
                errors["batch_id"] = "Choose an existing batch."
            else:
                batch = connection.execute(
                    """
                    SELECT b.id AS batch_id, b.product_id, b.received_date, b.expiry_date,
                           b.quantity_remaining, b.unit_cost, p.name AS product_name,
                           p.sku, p.unit
                    FROM stock_batches AS b
                    JOIN products AS p ON p.id = b.product_id
                    WHERE b.id = ? AND p.is_archived = 0
                    """,
                    (chosen_batch_id,),
                ).fetchone()
                if batch is None:
                    errors["batch_id"] = "Choose an existing batch belonging to an active product."

        business_date = None
        try:
            business_date = date.fromisoformat(form_data["business_date"])
            if business_date.isoformat() != form_data["business_date"] or business_date != today:
                raise ValueError
        except (TypeError, ValueError):
            errors["business_date"] = "Stock disposal and count corrections must be recorded using today's date."

        quantity = None
        if not re.fullmatch(r"[0-9]{1,19}", form_data["quantity"]):
            errors["quantity"] = "Quantity must be a whole number greater than zero."
        else:
            quantity = int(form_data["quantity"])
            if quantity < 1 or quantity > max_integer:
                errors["quantity"] = "Quantity must be a whole number greater than zero."

        reason = form_data["reason"]
        if not reason:
            errors["reason"] = "Enter a reason so the stock change can be audited."
        elif len(reason) > 200:
            errors["reason"] = "Use no more than 200 characters for the reason."
        if len(form_data["note"]) > 500:
            errors["note"] = "Use no more than 500 characters for the note."

        if batch is not None and business_date is not None:
            received_date = date.fromisoformat(batch["received_date"])
            if business_date < received_date:
                errors["business_date"] = "The action date cannot be earlier than the batch receipt date."
        if batch is not None and quantity is not None and quantity > 0:
            remaining = int(batch["quantity_remaining"])
            if operation_type in {"disposal", "adjustment_out"} and quantity > remaining:
                errors["quantity"] = f"Only {remaining} {batch['unit']} remain in this batch."
            elif operation_type == "adjustment_in" and quantity > max_integer - remaining:
                errors["quantity"] = "The corrected batch quantity would exceed the database's supported range."
            elif operation_type in {"disposal", "adjustment_out"} and remaining == 0:
                errors["quantity"] = "This batch has no remaining stock to remove."

        if errors:
            return render_template(
                "stock_actions/form.html", title="Waste & stock corrections",
                form_data=form_data, batches=batches, errors=errors,
                request_token=request_token, today=today.isoformat(),
            ), 400

        quantity_delta = int(quantity) if operation_type == "adjustment_in" else -int(quantity)
        try:
            cursor = connection.execute(
                """
                INSERT INTO stock_operations (
                    operation_type, request_token, business_date, reason, note
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    operation_type, request_token, business_date.isoformat(),
                    reason, form_data["note"] or None,
                ),
            )
            operation_id = cursor.lastrowid
            connection.execute(
                """
                INSERT INTO stock_movements (
                    operation_id, product_id, batch_id, quantity_delta
                ) VALUES (?, ?, ?, ?)
                """,
                (operation_id, int(batch["product_id"]), int(batch["batch_id"]), quantity_delta),
            )
            connection.commit()
        except sqlite3.IntegrityError:
            connection.rollback()
            duplicate = connection.execute(
                "SELECT operation_type FROM stock_operations WHERE request_token = ?",
                (request_token,),
            ).fetchone()
            if duplicate is not None and duplicate["operation_type"] == operation_type:
                flash("This stock action was already processed. No duplicate movement was created.", "info")
                return redirect(url_for("movements"))
            current_app.logger.exception("Stock action was rejected by a database constraint.")
            errors["_form"] = (
                "The stock action could not be saved because an inventory rule was not satisfied. "
                "No stock change was committed; review the batch and quantity."
            )
            return render_template(
                "stock_actions/form.html", title="Waste & stock corrections",
                form_data=form_data, batches=batches, errors=errors,
                request_token=request_token, today=today.isoformat(),
            ), 400
        except sqlite3.Error:
            connection.rollback()
            current_app.logger.exception("Unable to save stock action.")
            return render_template(
                "error.html", title="Stock action could not be saved", error_code=503,
                message="The stock action could not be saved. No stock change was committed; try again.",
            ), 503

        if operation_type == "disposal":
            disposal_value = int(quantity) * int(batch["unit_cost"])
            flash(
                f"Disposal recorded for {batch['product_name']}: {quantity} {batch['unit']} removed; "
                f"recorded cost value Rp {disposal_value:,}.",
                "success",
            )
        elif operation_type == "adjustment_in":
            flash(f"Stock count corrected: {quantity} {batch['unit']} added to batch #{batch['batch_id']}.", "success")
        else:
            flash(f"Stock count corrected: {quantity} {batch['unit']} removed from batch #{batch['batch_id']}.", "success")
        return redirect(url_for("movements"))


    @app.route("/settings", methods=["GET", "POST"])
    def settings():
        """View and update the local expiry-warning window."""
        if not Path(current_app.config["DATABASE"]).is_file():
            return render_template("setup.html", title="Initialize database"), 503

        connection = database.get_db()
        today = date.today()
        row = connection.execute(
            "SELECT expiry_warning_days FROM app_settings WHERE id = 1"
        ).fetchone()
        if row is None:
            current_app.logger.error("The application settings row is missing.")
            return render_template(
                "error.html", title="Settings unavailable", error_code=503,
                message="Application settings could not be loaded. Check the local database setup and try again.",
            ), 503

        current_days = int(row["expiry_warning_days"])
        form_value = str(current_days)
        error = None
        if request.method == "POST":
            if not _csrf_is_valid():
                abort(400)
            form_value = str(request.form.get("expiry_warning_days", "")).strip()
            if not re.fullmatch(r"[0-9]{1,3}", form_value):
                error = "Enter a whole number between 0 and 365."
            else:
                days = int(form_value)
                if days > 365:
                    error = "The expiry-warning window cannot exceed 365 days."
                else:
                    try:
                        connection.execute(
                            """
                            UPDATE app_settings
                            SET expiry_warning_days = ?,
                                updated_at_utc = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                            WHERE id = 1
                            """,
                            (days,),
                        )
                        connection.commit()
                    except sqlite3.Error:
                        connection.rollback()
                        current_app.logger.exception("Unable to update application settings.")
                        return render_template(
                            "error.html", title="Settings could not be saved", error_code=503,
                            message="The setting could not be saved. No configuration change was committed.",
                        ), 503
                    flash("Expiry-warning window updated successfully.", "success")
                    return redirect(url_for("settings"))

        response = render_template(
            "settings.html", title="Workspace settings",
            expiry_warning_days=form_value, current_days=current_days,
            error=error, today=today.isoformat(),
        )
        return (response, 400) if error else response

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
        request_token = secrets.token_urlsafe(32)
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
            request_token = str(request.form.get("request_token", "")).strip()
        if request.method == "GET":
            return render_template(
                "sales/form.html", title="Record a sale", products=products,
                form_data=form_data, errors={}, today=today.isoformat(),
                request_token=request_token,
            )
        if not _csrf_is_valid():
            abort(400)
        if not re.fullmatch(r"[A-Za-z0-9_-]{40,128}", request_token):
            abort(400)

        if not _begin_inventory_write(connection):
            return render_template(
                "error.html", title="Inventory busy", error_code=503,
                message="Another inventory change is being saved. No stock change was made; wait a moment and retry.",
            ), 503

        existing_operation = connection.execute(
            "SELECT operation_type FROM stock_operations WHERE request_token = ?",
            (request_token,),
        ).fetchone()
        if existing_operation is not None:
            if existing_operation["operation_type"] == "sale":
                flash("This sale was already processed. No duplicate transaction was created.", "info")
                return redirect(url_for("sales"))
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
            candidate_batches = connection.execute(
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
            batches = []
            for candidate in candidate_batches:
                batch_data = dict(candidate)
                batch_data["sellable_capacity"] = min(
                    int(batch_data["quantity_remaining"]),
                    _historical_sellable_capacity(
                        connection, int(batch_data["id"]), business_date.isoformat()
                    ),
                )
                if batch_data["sellable_capacity"] > 0:
                    batches.append(batch_data)
            available = sum(int(batch["sellable_capacity"]) for batch in batches)
            if quantity > available:
                errors["_form"] = (
                    f"Not enough sellable stock for this date. "
                    f"Available quantity: {available} {product['unit']}."
                )
            else:
                quantity_left = quantity
                for batch in batches:
                    allocation = min(quantity_left, int(batch["sellable_capacity"]))
                    if allocation > 0:
                        allocations.append((int(batch["id"]), allocation))
                        quantity_left -= allocation
                    if quantity_left == 0:
                        break

        if errors:
            return render_template(
                "sales/form.html", title="Record a sale", products=products,
                form_data=form_data, errors=errors, today=today.isoformat(),
                request_token=request_token,
            ), 400

        try:
            cursor = connection.execute(
                """
                INSERT INTO stock_operations (operation_type, request_token, business_date, note)
                VALUES ('sale', ?, ?, ?)
                """,
                (
                    request_token, business_date.isoformat(),
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
            duplicate = connection.execute(
                "SELECT operation_type FROM stock_operations WHERE request_token = ?",
                (request_token,),
            ).fetchone()
            if duplicate is not None and duplicate["operation_type"] == "sale":
                flash("This sale was already processed. No duplicate transaction was created.", "info")
                return redirect(url_for("sales"))
            current_app.logger.exception("Sale was rejected by the database.")
            errors["_form"] = (
                "The sale could not be saved because an inventory rule was not satisfied. "
                "No stock was changed; review the details and try again."
            )
            return render_template(
                "sales/form.html", title="Record a sale", products=products,
                form_data=form_data, errors=errors, today=today.isoformat(),
                request_token=request_token,
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
