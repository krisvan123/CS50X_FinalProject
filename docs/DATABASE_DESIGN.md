# WarungWise — Database Design

**Phase:** 3 — Database Design  
**Status:** Initial schema drafted and checked in an isolated SQLite database; application integration has not started  
**Related documents:** [Project Brief and Scope](PROJECT_BRIEF.md) · [Requirements and User Flows](REQUIREMENTS_AND_USER_FLOWS.md)  
**Schema:** [schema.sql](../schema.sql)

## 1. Design Goals

The database supports product management, batch-level expiry tracking, sales, traceable stock movements, and reporting. Correctness and auditability take priority over premature optimization.

The first release uses SQLite locally for one shop. Inventory quantities are whole numbers and money is stored as integer Indonesian rupiah (IDR), avoiding floating-point rounding in prices and costs. A sale line stores its selling-price snapshot so a later product price change does not rewrite historical revenue.

## 2. Entities and Relationships

| Entity | Responsibility | Relationships |
|---|---|---|
| products | Product identity, current/default prices, unit, minimum stock, restock settings, expiry preference, archive status | One product has many batches and sale items |
| stock_operations | Immutable header with operation type, unique request token, UTC timestamp, local business date, reason, and note | One operation has one or more movements |
| stock_batches | Batch identity, product, receipt date, optional expiry, original quantity, current quantity, and actual unit cost | One batch belongs to one product and has many movements |
| sales | Sale header linked to a sale operation | One sale has multiple sale items |
| sale_items | Product, quantity, and selling-price snapshot for each sale line | A sale line may consume multiple batches through movements |
| stock_movements | Signed batch quantity changes; movement type comes from its operation header | Each movement links to an operation and a batch; sale movements also link to a sale item |
| app_settings | Application-wide settings; initially the expiry-warning window | Single settings row |

Principal relationships: one product to many batches, one sale to many sale items, and one operation to many stock movements. Historical records use restrictive foreign keys rather than cascading deletion. Used products are archived instead of deleted.

## 3. Table Definitions

### products

- **id:** integer primary key.
- **name:** required non-empty text.
- **sku:** optional, unique without regard to letter case when provided.
- **category:** optional text.
- **unit:** required unit such as bottle, pack, or piece.
- **cost_price:** current/reference unit cost in IDR; integer, non-negative.
- **selling_price:** current/default sale price in IDR; integer, positive.
- **minimum_stock:** non-negative low-stock threshold.
- **lead_time_days:** integer of at least one day.
- **safety_stock:** non-negative integer.
- **tracks_expiry:** boolean-style integer restricted to 0 or 1.
- **is_archived:** boolean-style integer restricted to 0 or 1.
- **created_at_utc / updated_at_utc:** UTC timestamps in a consistent ISO 8601 representation.

The application trims input and normalizes SKU values before storage. The product's cost is a reference for future receipts; each batch stores the actual unit cost for that receipt. Expiry-tracking preference cannot change after the first batch exists, preventing older batches from becoming inconsistent with product settings.

### stock_operations

- **id:** integer primary key.
- **operation_type:** receipt, sale, disposal, adjustment_out, or adjustment_in.
- **request_token:** unique required token for duplicate-submission protection.
- **occurred_at_utc:** timestamp recorded in UTC.
- **business_date:** required local business date in YYYY-MM-DD format.
- **reason:** required for disposal and either adjustment direction; absent for receipt and sale.
- **note:** optional explanatory text.

An operation header groups all movement rows caused by one user action. This allows a single sale that consumes multiple batches to remain one idempotent operation. The local business date is stored separately from the UTC timestamp so expiry decisions do not depend on the database server's UTC calendar date.

### stock_batches

- **id:** integer primary key.
- **product_id:** foreign key to products.
- **receipt_operation_id:** unique foreign key to the operation that created the batch.
- **received_date:** required valid calendar date in YYYY-MM-DD format.
- **expiry_date:** required for expiry-tracked products; otherwise null.
- **quantity_received:** original positive whole quantity.
- **quantity_remaining:** current balance, updated by a database trigger.
- **unit_cost:** actual unit cost for the batch in IDR; non-negative integer.
- **created_at_utc:** UTC creation timestamp.

Each receipt creates a new batch. Its product identity, receipt date, expiry date, original quantity, and actual unit cost are immutable. Its balance starts at zero and becomes available through the positive receipt movement. The database keeps the balance non-negative. The original received quantity remains a historical reference; a documented positive correction can make the current balance exceed the original receipt quantity, and that difference remains visible in the movement ledger.

### sales and sale_items

**sales** contains an integer primary key and a unique reference to its sale operation. Its timestamp and business date come from that operation, avoiding duplicated values.

**sale_items** contains an integer primary key, sale ID, product ID, positive whole quantity, and positive selling-price snapshot in IDR. A product may appear only once per sale; the application combines repeated selections before saving. Historical sales and sale items are append-only in this version.

### stock_movements

Each row contains an integer primary key, operation ID, product ID, batch ID, optional sale-item ID, and non-zero signed quantity delta. Composite foreign keys require a movement's product to match its batch and, for sales, the referenced sale item. A unique operation-and-batch pair prevents duplicate movements for the same batch within one operation.

The movement type is read from the linked operation header rather than duplicated on every movement row. Receipt and documented inbound-adjustment quantities are positive; sale, disposal, and outbound-adjustment quantities are negative. An inbound adjustment is only for correcting a count on an existing batch and requires a reason; a new delivery must use the receipt workflow. Movements and operation headers are immutable so history cannot be silently rewritten.

### app_settings

A singleton row stores the expiry-warning window. The schema inserts an initial value of 30 days and prevents negative values. The application must update the settings timestamp whenever the window changes.

## 4. Stock-Balance Strategy

The database keeps an operational batch balance and an append-only movement ledger. An AFTER INSERT trigger on stock_movements updates stock_batches.quantity_remaining, so application code does not separately update the two values.

The database checks that:
- a batch is created through a receipt operation for an active product;
- expiry dates follow the product's expiry-tracking setting;
- a receipt movement matches the batch's original received quantity;
- sale movements link to a sale item in the same sale operation;
- movements do not make a batch balance negative;
- expired batches cannot satisfy sales, using the operation's business date;
- one request token cannot create multiple stock-changing operations.

Two audit views support verification:

- **v_batch_balance_audit** compares the stored batch balance against the sum of movement deltas. Its difference should be zero for every batch.
- **v_sale_item_allocation_audit** compares each sale line's quantity with the total allocated quantity from batches. Its difference should be zero after a completed sale.

SQLite constraints cannot enforce all cross-row invariants at transaction commit. The application service must ensure that each sale line's allocated quantity equals the quantity sold and that all sale lines succeed together. Automated tests will verify the audit views.

## 5. FEFO and Expiry Rules

For products with expiry tracking, stock allocation order is: earliest expiry date that has not passed the operation's business date, then earliest receipt date, then lowest batch ID for deterministic tie-breaking. An expiry date equal to the business date remains eligible for sale that day. Non-expiry-tracked products have a null expiry date and use receipt-date FIFO ordering.

Approaching-expiry alerts apply to batches with remaining quantity and expiry dates inside the configured warning window. Expired and approaching-expiry counts must be labelled as product counts or batch counts rather than mixing the two. Audit timestamps use UTC; expiry comparisons use the local business date provided by the application.

## 6. Money and Reporting

All monetary values use integer IDR. Floating-point values must not be used for prices or quantities.

- **Sales revenue:** sum of sale-item quantity multiplied by its selling-price snapshot.
- **Cost of goods sold:** for sale movements, sum of the absolute quantity delta multiplied by the linked batch's unit cost.
- **Estimated gross profit:** revenue minus cost of goods sold for the same period. It is not net profit.
- **Recorded disposal value:** for disposal operations, sum of disposed quantity multiplied by the batch unit cost. An expiry warning alone is not a realized disposal loss.
- **Restock recommendation:** target stock equals average daily sales multiplied by lead time, plus safety stock; suggested restock equals the larger of zero and target stock minus sellable stock.

Reports must be derived from saved records. Date-filtered sales reports should use the operation's business date so local-date filters are not confused with UTC timestamps.

## 7. Constraints, Triggers, and Indexes

The schema includes:
- foreign keys with restrictive deletion rules to protect history;
- checks for required text, non-negative costs and thresholds, positive quantities/prices, valid dates, and supported operation types;
- a case-insensitive unique SKU index and indexes for product search, category, batch product/expiry lookup, and stock-movement lookup;
- triggers for receipt linkage, archived-product restrictions, locked expiry-tracking settings, sale-operation linkage, batch balance updates, expired-sale rejection, and immutable operation/movement history.

Every application database connection must enable SQLite foreign-key enforcement. The schema enables it for the connection executing the file; the future database helper must also run PRAGMA foreign_keys = ON for each connection.

## 8. Initialization and Data Safety

Run the Python standard-library initializer from the repository root:

    python init_db.py

The script creates the local database at instance/warungwise.db, applies schema.sql, checks SQLite integrity and foreign-key consistency, and reports success. It refuses to overwrite an existing database. It inserts the default expiry-warning setting but does not create demo products or transactions. The instance directory and local database files are excluded from source control by .gitignore.

The schema file uses non-destructive table, index, trigger, and view creation statements. It does not drop tables or delete records. SQLite foreign-key enforcement is connection-specific, so the future application database helper must run PRAGMA foreign_keys = ON for every connection, not only during initialization.

This is an initial schema, not a migration system. IF NOT EXISTS does not update a table that already exists with an older definition. Once meaningful data exists, schema changes require explicit reviewed migrations or a disposable test database. The initializer refuses to reuse an existing database; do not delete a populated database just to make a schema update work.

## 9. Transaction Workflows for Implementation

### Stock receipt

1. Validate product status, positive quantity, cost, receipt date, and expiry rules.
2. Begin a write transaction before making changes.
3. Create a receipt operation with a unique request token and local business date.
4. Insert a batch with quantity_remaining set to zero.
5. Insert the positive receipt movement; a database trigger updates the batch balance.
6. Commit only if all steps succeed; otherwise roll back the operation, batch, and movement together.

### Sale

1. Validate every sale line and the requested quantity.
2. Begin a write transaction before the final stock checks to prevent a check-then-write race.
3. Create a sale operation and sale header with a unique request token.
4. Insert sale items with selling-price snapshots.
5. Allocate each line from eligible batches in FEFO order and insert negative movements linked to each sale item.
6. Verify sale-allocation and batch-balance audit differences are zero.
7. Commit the entire sale or roll back every row if any line cannot be fulfilled.

If a completed request token is submitted again, the application must not replay its stock changes. It should identify the existing operation and return the existing result or an understandable duplicate-submission message.

### Disposal or stock-count adjustment

1. Validate the existing batch, positive absolute quantity, and required reason.
2. Start a transaction and create the operation with a unique request token and business date.
3. For disposal or an outbound correction, insert a negative movement. For a documented inbound count correction, insert a positive movement against the existing batch. The trigger maintains the balance and rejects an overdraw or invalid movement direction.
4. A positive correction cannot be used to record a new delivery; new deliveries must use the receipt workflow so a new batch and its cost are captured.
5. Commit the operation and movement together, or roll both back.

## 10. Preliminary Schema Validation

Before commit, the schema was executed in an isolated in-memory SQLite database. The following checks succeeded:

- Schema creation completed.
- A receipt increased batch balance and a sale decreased it.
- Batch-balance and sale-allocation audit differences were zero for the exercised workflow.
- An overdrawn movement was rejected without changing the balance.
- A sale movement from an expired batch was rejected.
- A duplicate case-insensitive SKU was rejected.
- Re-executing the schema did not require deleting the test database.

These are preliminary checks of the schema in isolation, not full application tests. The Flask application, user interface, and end-to-end workflows have not yet been implemented.

## 11. Definition of Done for Phase 3

Phase 3 is documented when entities, relationships, constraints, transaction boundaries, and deletion policies are defined; balances and audit rules are explicit; an initial schema can initialize a database without destructive reset statements; and important constraints have been checked in a temporary SQLite database.
