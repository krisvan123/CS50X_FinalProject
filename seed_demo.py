"""Create a safe, fictional dataset for the WarungWise demo.

The dataset lives in instance/warungwise-demo.db by default, separate from the
normal local database. Existing data is never overwritten or mixed with demos.
"""

# AI-use disclosure: ChatGPT assisted with drafting the optional demo dataset.
# The project author should inspect the sample business records before presenting.
from __future__ import annotations

import argparse
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from init_db import initialize_database


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "instance" / "warungwise-demo.db"


# Prices are whole Indonesian rupiah. All names, SKUs, transactions, and notes
# below are synthetic; transaction and expiry dates shift relative to the run date.
DEMO_PRODUCTS: tuple[dict[str, Any], ...] = (
    {
        "name": "Aqua Mineral Water 600 mL", "sku": "WW-DEMO-WATER-001",
        "category": "Beverages", "unit": "bottle", "cost_price": 1800,
        "selling_price": 2500, "minimum_stock": 12, "lead_time_days": 2,
        "safety_stock": 6, "tracks_expiry": 0,
        "batches": ({"received_days_ago": 30, "expiry_days_from_today": None,
                     "quantity": 55, "unit_cost": 1800},),
    },
    {
        "name": "Chicken Instant Noodles", "sku": "WW-DEMO-NOODLE-001",
        "category": "Instant food", "unit": "pack", "cost_price": 2500,
        "selling_price": 3500, "minimum_stock": 20, "lead_time_days": 3,
        "safety_stock": 8, "tracks_expiry": 1,
        "batches": (
            {"received_days_ago": 24, "expiry_days_from_today": 8,
             "quantity": 48, "unit_cost": 2500},
            {"received_days_ago": 9, "expiry_days_from_today": 75,
             "quantity": 60, "unit_cost": 2600},
        ),
    },
    {
        "name": "UHT Milk 1 L", "sku": "WW-DEMO-MILK-001",
        "category": "Dairy", "unit": "carton", "cost_price": 12000,
        "selling_price": 15500, "minimum_stock": 8, "lead_time_days": 2,
        "safety_stock": 3, "tracks_expiry": 1,
        "batches": ({"received_days_ago": 12, "expiry_days_from_today": 4,
                     "quantity": 18, "unit_cost": 12000},),
    },
    {
        "name": "Chocolate Biscuits", "sku": "WW-DEMO-BISCUIT-001",
        "category": "Snacks", "unit": "pack", "cost_price": 4500,
        "selling_price": 6000, "minimum_stock": 6, "lead_time_days": 5,
        "safety_stock": 2, "tracks_expiry": 1,
        "batches": ({"received_days_ago": 17, "expiry_days_from_today": -2,
                     "quantity": 16, "unit_cost": 4500},),
    },
    {
        "name": "Cooking Oil 1 L", "sku": "WW-DEMO-OIL-001",
        "category": "Kitchen essentials", "unit": "pouch", "cost_price": 16000,
        "selling_price": 19500, "minimum_stock": 5, "lead_time_days": 3,
        "safety_stock": 2, "tracks_expiry": 0,
        "batches": ({"received_days_ago": 28, "expiry_days_from_today": None,
                     "quantity": 24, "unit_cost": 16000},),
    },
    {
        "name": "Rice 5 kg", "sku": "WW-DEMO-RICE-001",
        "category": "Staples", "unit": "bag", "cost_price": 65000,
        "selling_price": 72000, "minimum_stock": 3, "lead_time_days": 4,
        "safety_stock": 1, "tracks_expiry": 0,
        "batches": ({"received_days_ago": 30, "expiry_days_from_today": None,
                     "quantity": 12, "unit_cost": 65000},),
    },
    {
        "name": "Eggs 10-Pack", "sku": "WW-DEMO-EGGS-001",
        "category": "Fresh food", "unit": "pack", "cost_price": 23000,
        "selling_price": 28000, "minimum_stock": 6, "lead_time_days": 1,
        "safety_stock": 4, "tracks_expiry": 1,
        "batches": ({"received_days_ago": 10, "expiry_days_from_today": 3,
                     "quantity": 30, "unit_cost": 23000},),
    },
    {
        "name": "Instant Coffee Sachets", "sku": "WW-DEMO-COFFEE-001",
        "category": "Beverages", "unit": "sachet", "cost_price": 800,
        "selling_price": 1200, "minimum_stock": 10, "lead_time_days": 3,
        "safety_stock": 5, "tracks_expiry": 1,
        "batches": ({"received_days_ago": 25, "expiry_days_from_today": 70,
                     "quantity": 80, "unit_cost": 800},),
    },
    {
        "name": "Granulated Sugar 1 kg", "sku": "WW-DEMO-SUGAR-001",
        "category": "Staples", "unit": "pack", "cost_price": 12500,
        "selling_price": 15000, "minimum_stock": 8, "lead_time_days": 2,
        "safety_stock": 4, "tracks_expiry": 0,
        "batches": ({"received_days_ago": 25, "expiry_days_from_today": None,
                     "quantity": 20, "unit_cost": 12500},),
    },
    {
        "name": "Dishwashing Liquid 650 mL", "sku": "WW-DEMO-SOAP-001",
        "category": "Household", "unit": "pouch", "cost_price": 7000,
        "selling_price": 9000, "minimum_stock": 5, "lead_time_days": 5,
        "safety_stock": 2, "tracks_expiry": 0,
        "batches": ({"received_days_ago": 20, "expiry_days_from_today": None,
                     "quantity": 12, "unit_cost": 7000},),
    },
    {
        "name": "Sardines in Tomato Sauce", "sku": "WW-DEMO-SARDINE-001",
        "category": "Canned food", "unit": "can", "cost_price": 11000,
        "selling_price": 14000, "minimum_stock": 4, "lead_time_days": 7,
        "safety_stock": 2, "tracks_expiry": 1,
        "batches": ({"received_days_ago": 22, "expiry_days_from_today": 120,
                     "quantity": 20, "unit_cost": 11000},),
    },
    {
        "name": "Potato Chips", "sku": "WW-DEMO-CHIPS-001",
        "category": "Snacks", "unit": "pack", "cost_price": 15000,
        "selling_price": 18000, "minimum_stock": 8, "lead_time_days": 3,
        "safety_stock": 3, "tracks_expiry": 1,
        "batches": ({"received_days_ago": 18, "expiry_days_from_today": 18,
                     "quantity": 20, "unit_cost": 15000},),
    },
)


# Each sale is a separate counter transaction. Offsets are relative to today.
# Sales are inserted in chronological order and never consume expired stock.
DEMO_SALES: tuple[dict[str, Any], ...] = (
    {"sku": "WW-DEMO-WATER-001", "batch": 0, "days_ago": 13, "quantity": 5, "note": "Morning counter sale"},
    {"sku": "WW-DEMO-WATER-001", "batch": 0, "days_ago": 8, "quantity": 7, "note": "Afternoon counter sale"},
    {"sku": "WW-DEMO-WATER-001", "batch": 0, "days_ago": 0, "quantity": 3, "note": "Demo sale today"},
    {"sku": "WW-DEMO-NOODLE-001", "batch": 0, "days_ago": 17, "quantity": 5, "note": "Instant-food counter sale"},
    {"sku": "WW-DEMO-NOODLE-001", "batch": 0, "days_ago": 12, "quantity": 4, "note": "Instant-food counter sale"},
    {"sku": "WW-DEMO-NOODLE-001", "batch": 0, "days_ago": 6, "quantity": 6, "note": "Instant-food counter sale"},
    {"sku": "WW-DEMO-NOODLE-001", "batch": 0, "days_ago": 0, "quantity": 2, "note": "Demo sale today"},
    {"sku": "WW-DEMO-MILK-001", "batch": 0, "days_ago": 10, "quantity": 2, "note": "Dairy counter sale"},
    {"sku": "WW-DEMO-MILK-001", "batch": 0, "days_ago": 4, "quantity": 3, "note": "Dairy counter sale"},
    {"sku": "WW-DEMO-OIL-001", "batch": 0, "days_ago": 14, "quantity": 3, "note": "Kitchen essentials sale"},
    {"sku": "WW-DEMO-OIL-001", "batch": 0, "days_ago": 7, "quantity": 4, "note": "Kitchen essentials sale"},
    {"sku": "WW-DEMO-OIL-001", "batch": 0, "days_ago": 0, "quantity": 1, "note": "Demo sale today"},
    {"sku": "WW-DEMO-RICE-001", "batch": 0, "days_ago": 9, "quantity": 1, "note": "Staples counter sale"},
    {"sku": "WW-DEMO-RICE-001", "batch": 0, "days_ago": 2, "quantity": 2, "note": "Staples counter sale"},
    {"sku": "WW-DEMO-EGGS-001", "batch": 0, "days_ago": 6, "quantity": 4, "note": "Fresh-food counter sale"},
    {"sku": "WW-DEMO-EGGS-001", "batch": 0, "days_ago": 1, "quantity": 6, "note": "Fresh-food counter sale"},
    {"sku": "WW-DEMO-COFFEE-001", "batch": 0, "days_ago": 18, "quantity": 10, "note": "Beverage counter sale"},
    {"sku": "WW-DEMO-COFFEE-001", "batch": 0, "days_ago": 11, "quantity": 12, "note": "Beverage counter sale"},
    {"sku": "WW-DEMO-COFFEE-001", "batch": 0, "days_ago": 3, "quantity": 8, "note": "Beverage counter sale"},
    {"sku": "WW-DEMO-SUGAR-001", "batch": 0, "days_ago": 13, "quantity": 4, "note": "Staples counter sale"},
    {"sku": "WW-DEMO-SUGAR-001", "batch": 0, "days_ago": 6, "quantity": 3, "note": "Staples counter sale"},
    {"sku": "WW-DEMO-SUGAR-001", "batch": 0, "days_ago": 2, "quantity": 4, "note": "Staples counter sale"},
    {"sku": "WW-DEMO-SUGAR-001", "batch": 0, "days_ago": 0, "quantity": 2, "note": "Demo sale today"},
    {"sku": "WW-DEMO-SOAP-001", "batch": 0, "days_ago": 8, "quantity": 2, "note": "Household essentials sale"},
    {"sku": "WW-DEMO-SOAP-001", "batch": 0, "days_ago": 2, "quantity": 3, "note": "Household essentials sale"},
    {"sku": "WW-DEMO-SARDINE-001", "batch": 0, "days_ago": 7, "quantity": 3, "note": "Canned-food counter sale"},
    {"sku": "WW-DEMO-SARDINE-001", "batch": 0, "days_ago": 1, "quantity": 4, "note": "Canned-food counter sale"},
    {"sku": "WW-DEMO-CHIPS-001", "batch": 0, "days_ago": 9, "quantity": 3, "note": "Snack counter sale"},
    {"sku": "WW-DEMO-CHIPS-001", "batch": 0, "days_ago": 3, "quantity": 4, "note": "Snack counter sale"},
)


def _date_days_ago(today: date, days: int) -> str:
    return (today - timedelta(days=days)).isoformat()


def _date_relative_to_today(today: date, days: int) -> str:
    return (today + timedelta(days=days)).isoformat()


def _insert_operation(
    connection: sqlite3.Connection,
    operation_type: str,
    request_token: str,
    business_date: str,
    note: str,
    reason: str | None = None,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO stock_operations (
            operation_type, request_token, business_date, reason, note
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (operation_type, request_token, business_date, reason, note),
    )
    return int(cursor.lastrowid)


def _table_count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _audit_is_balanced(connection: sqlite3.Connection) -> bool:
    for view_name in ("v_batch_balance_audit", "v_sale_item_allocation_audit"):
        if connection.execute(
            f"SELECT COUNT(*) FROM {view_name} WHERE difference <> 0"
        ).fetchone()[0]:
            return False
    return not connection.execute("PRAGMA foreign_key_check").fetchall()


def _already_seeded(connection: sqlite3.Connection) -> bool:
    skus = {
        row[0] for row in connection.execute("SELECT sku FROM products").fetchall()
    }
    tokens = [
        row[0] for row in connection.execute(
            "SELECT request_token FROM stock_operations"
        ).fetchall()
    ]
    expected_skus = {product["sku"] for product in DEMO_PRODUCTS}
    expected_batches = sum(len(product["batches"]) for product in DEMO_PRODUCTS)
    return (
        skus == expected_skus
        and len(skus) == len(DEMO_PRODUCTS)
        and len(tokens) == len(DEMO_PRODUCTS) + len(DEMO_SALES) + 2
        and all(token.startswith("demo-") for token in tokens)
        and _table_count(connection, "stock_batches") == expected_batches
        and _table_count(connection, "sales") == len(DEMO_SALES)
        and _table_count(connection, "sale_items") == len(DEMO_SALES)
        and _table_count(connection, "stock_movements") == len(tokens)
        and _audit_is_balanced(connection)
    )


def seed_demo_database(database_path: Path = DEFAULT_DATABASE_PATH) -> dict[str, Any]:
    """Create fictional sample records in a dedicated, initially empty database.

    A completed demo seed is an idempotent no-op. Any unrelated or partial
    inventory causes a refusal, so the script cannot silently mix datasets.
    """
    database_path = Path(database_path).expanduser()
    if not database_path.exists():
        initialize_database(database_path=database_path)
    if not database_path.is_file():
        raise FileNotFoundError(f"Demo database is not a file: {database_path}")

    connection = sqlite3.connect(str(database_path), timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    try:
        connection.execute("BEGIN IMMEDIATE")
        counts = {
            table: _table_count(connection, table)
            for table in (
                "products", "stock_operations", "stock_batches", "sales",
                "sale_items", "stock_movements",
            )
        }

        if _already_seeded(connection):
            connection.rollback()
            return {
                "status": "already_seeded",
                "database": str(database_path.resolve()),
                **counts,
            }

        if any(counts.values()):
            raise ValueError(
                "The selected database already contains records and was not changed. "
                "Choose a new, empty demo database or back up and clear only the "
                "intended demo database before reseeding."
            )

        today = date.today()
        product_ids: dict[str, int] = {}
        batch_ids: dict[tuple[str, int], int] = {}

        for product in DEMO_PRODUCTS:
            cursor = connection.execute(
                """
                INSERT INTO products (
                    name, sku, category, unit, cost_price, selling_price,
                    minimum_stock, lead_time_days, safety_stock, tracks_expiry
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product["name"], product["sku"], product["category"],
                    product["unit"], product["cost_price"], product["selling_price"],
                    product["minimum_stock"], product["lead_time_days"],
                    product["safety_stock"], product["tracks_expiry"],
                ),
            )
            product_ids[product["sku"]] = int(cursor.lastrowid)

        for product in DEMO_PRODUCTS:
            sku = product["sku"]
            product_id = product_ids[sku]
            for batch_index, batch in enumerate(product["batches"]):
                received_date = _date_days_ago(today, batch["received_days_ago"])
                expiry_offset = batch["expiry_days_from_today"]
                expiry_date = (
                    _date_relative_to_today(today, expiry_offset)
                    if expiry_offset is not None
                    else None
                )
                operation_id = _insert_operation(
                    connection,
                    "receipt",
                    f"demo-receipt-{sku.lower()}-{batch_index + 1:02d}",
                    received_date,
                    f"Fictional demo delivery for {product['name']}.",
                )
                cursor = connection.execute(
                    """
                    INSERT INTO stock_batches (
                        product_id, receipt_operation_id, received_date, expiry_date,
                        quantity_received, quantity_remaining, unit_cost
                    ) VALUES (?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        product_id, operation_id, received_date, expiry_date,
                        batch["quantity"], batch["unit_cost"],
                    ),
                )
                batch_id = int(cursor.lastrowid)
                batch_ids[(sku, batch_index)] = batch_id
                connection.execute(
                    """
                    INSERT INTO stock_movements (
                        operation_id, product_id, batch_id, quantity_delta
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (operation_id, product_id, batch_id, batch["quantity"]),
                )

        # Oldest business dates must be written first for an auditable history.
        chronological_sales = sorted(
            enumerate(DEMO_SALES, start=1),
            key=lambda pair: (-int(pair[1]["days_ago"]), pair[0]),
        )
        for sale_number, sale in chronological_sales:
            sku = str(sale["sku"])
            product = next(item for item in DEMO_PRODUCTS if item["sku"] == sku)
            business_date = _date_days_ago(today, int(sale["days_ago"]))
            operation_id = _insert_operation(
                connection,
                "sale",
                f"demo-sale-{sale_number:03d}-{sku.lower()}",
                business_date,
                str(sale["note"]),
            )
            cursor = connection.execute(
                "INSERT INTO sales (operation_id) VALUES (?)",
                (operation_id,),
            )
            sale_id = int(cursor.lastrowid)
            cursor = connection.execute(
                """
                INSERT INTO sale_items (
                    sale_id, product_id, quantity, unit_selling_price
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    sale_id, product_ids[sku], int(sale["quantity"]),
                    int(product["selling_price"]),
                ),
            )
            sale_item_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO stock_movements (
                    operation_id, product_id, batch_id, sale_item_id, quantity_delta
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    operation_id, product_ids[sku],
                    batch_ids[(sku, int(sale["batch"]))], sale_item_id,
                    -int(sale["quantity"]),
                ),
            )

        # Include one auditable disposal and one positive count correction.
        chip_sku = "WW-DEMO-CHIPS-001"
        disposal_operation = _insert_operation(
            connection, "disposal", "demo-disposal-chips-damaged",
            today.isoformat(), "Two packs removed after packaging damage.",
            reason="Damaged packaging",
        )
        connection.execute(
            """
            INSERT INTO stock_movements (
                operation_id, product_id, batch_id, quantity_delta
            ) VALUES (?, ?, ?, -2)
            """,
            (disposal_operation, product_ids[chip_sku], batch_ids[(chip_sku, 0)]),
        )

        water_sku = "WW-DEMO-WATER-001"
        adjustment_operation = _insert_operation(
            connection, "adjustment_in", "demo-adjustment-water-count",
            today.isoformat(), "Two bottles were found during a shelf count.",
            reason="Physical count reconciliation",
        )
        connection.execute(
            """
            INSERT INTO stock_movements (
                operation_id, product_id, batch_id, quantity_delta
            ) VALUES (?, ?, ?, 2)
            """,
            (adjustment_operation, product_ids[water_sku], batch_ids[(water_sku, 0)]),
        )

        if not _audit_is_balanced(connection):
            raise RuntimeError("Demo data failed the foreign-key or inventory audit checks.")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise RuntimeError(f"Demo database integrity check failed: {integrity}")

        connection.commit()
        final_counts = {
            table: _table_count(connection, table)
            for table in (
                "products", "stock_operations", "stock_batches", "sales",
                "sale_items", "stock_movements",
            )
        }
        return {
            "status": "seeded",
            "database": str(database_path.resolve()),
            **final_counts,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create fictional WarungWise demo records in a separate SQLite database."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help=f"demo database path (default: {DEFAULT_DATABASE_PATH})",
    )
    args = parser.parse_args()

    try:
        result = seed_demo_database(args.database)
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as error:
        print(f"Demo data was not seeded: {error}")
        return 1

    print(f"Demo dataset status: {result['status']}")
    print(f"Database: {result['database']}")
    print(f"Products: {result['products']}")
    print(f"Stock batches: {result['stock_batches']}")
    print(f"Sales: {result['sales']}")
    print(f"Stock operations: {result['stock_operations']}")
    print("All demo records are fictional.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
