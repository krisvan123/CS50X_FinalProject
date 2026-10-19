"""WarungWise Flask application entry point.

The current phase provides a read-only dashboard foundation and a health
endpoint. Product and stock-changing routes will be added in later phases.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from flask import Flask, current_app, jsonify, render_template

import database


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
