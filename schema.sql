PRAGMA foreign_keys = ON;
BEGIN;

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    sku TEXT CHECK (sku IS NULL OR length(trim(sku)) > 0),
    category TEXT,
    unit TEXT NOT NULL CHECK (length(trim(unit)) > 0),
    cost_price INTEGER NOT NULL DEFAULT 0 CHECK (cost_price >= 0),
    selling_price INTEGER NOT NULL CHECK (selling_price > 0),
    minimum_stock INTEGER NOT NULL DEFAULT 0 CHECK (minimum_stock >= 0),
    lead_time_days INTEGER NOT NULL DEFAULT 1 CHECK (lead_time_days >= 1),
    safety_stock INTEGER NOT NULL DEFAULT 0 CHECK (safety_stock >= 0),
    tracks_expiry INTEGER NOT NULL CHECK (tracks_expiry IN (0, 1)),
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_products_sku_nocase
ON products (sku COLLATE NOCASE) WHERE sku IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_products_active_name
ON products (is_archived, name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_products_category
ON products (category);

CREATE TABLE IF NOT EXISTS stock_operations (
    id INTEGER PRIMARY KEY,
    operation_type TEXT NOT NULL CHECK (operation_type IN ('receipt', 'sale', 'disposal', 'adjustment_out', 'adjustment_in')),
    request_token TEXT NOT NULL UNIQUE CHECK (length(trim(request_token)) > 0),
    occurred_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    business_date TEXT NOT NULL CHECK (
        length(business_date) = 10 AND date(business_date, '+0 days') = business_date
    ),
    reason TEXT,
    note TEXT,
    CHECK (
        (operation_type IN ('disposal', 'adjustment_out', 'adjustment_in') AND reason IS NOT NULL AND length(trim(reason)) > 0)
        OR (operation_type IN ('receipt', 'sale') AND reason IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS stock_batches (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL,
    receipt_operation_id INTEGER NOT NULL UNIQUE,
    received_date TEXT NOT NULL CHECK (
        length(received_date) = 10
        AND date(received_date, '+0 days') = received_date
    ),
    expiry_date TEXT CHECK (
        expiry_date IS NULL
        OR (length(expiry_date) = 10 AND date(expiry_date, '+0 days') = expiry_date)
    ),
    quantity_received INTEGER NOT NULL CHECK (quantity_received > 0),
    quantity_remaining INTEGER NOT NULL DEFAULT 0 CHECK (
        quantity_remaining >= 0
    ),
    unit_cost INTEGER NOT NULL CHECK (unit_cost >= 0),
    created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
    FOREIGN KEY (receipt_operation_id) REFERENCES stock_operations(id) ON DELETE RESTRICT,
    UNIQUE (id, product_id),
    CHECK (expiry_date IS NULL OR expiry_date >= received_date)
);

CREATE INDEX IF NOT EXISTS idx_batches_product_received
ON stock_batches (product_id, received_date);
CREATE INDEX IF NOT EXISTS idx_batches_expiry
ON stock_batches (expiry_date);
CREATE INDEX IF NOT EXISTS idx_batches_product_expiry
ON stock_batches (product_id, expiry_date);

CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY,
    operation_id INTEGER NOT NULL UNIQUE,
    FOREIGN KEY (operation_id) REFERENCES stock_operations(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS sale_items (
    id INTEGER PRIMARY KEY,
    sale_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_selling_price INTEGER NOT NULL CHECK (unit_selling_price > 0),
    FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE RESTRICT,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
    UNIQUE (sale_id, product_id),
    UNIQUE (id, product_id)
);

CREATE INDEX IF NOT EXISTS idx_sale_items_product
ON sale_items (product_id);

CREATE TABLE IF NOT EXISTS stock_movements (
    id INTEGER PRIMARY KEY,
    operation_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    batch_id INTEGER NOT NULL,
    sale_item_id INTEGER,
    quantity_delta INTEGER NOT NULL CHECK (quantity_delta <> 0),
    FOREIGN KEY (operation_id) REFERENCES stock_operations(id) ON DELETE RESTRICT,
    FOREIGN KEY (batch_id, product_id) REFERENCES stock_batches(id, product_id) ON DELETE RESTRICT,
    FOREIGN KEY (sale_item_id, product_id) REFERENCES sale_items(id, product_id) ON DELETE RESTRICT,
    UNIQUE (operation_id, batch_id)
);

CREATE INDEX IF NOT EXISTS idx_movements_batch
ON stock_movements (batch_id);
CREATE INDEX IF NOT EXISTS idx_movements_operation
ON stock_movements (operation_id);
CREATE INDEX IF NOT EXISTS idx_movements_product
ON stock_movements (product_id);

CREATE TRIGGER IF NOT EXISTS trg_batch_receipt_operation
BEFORE INSERT ON stock_batches
BEGIN
    SELECT CASE
        WHEN (SELECT operation_type FROM stock_operations WHERE id = NEW.receipt_operation_id) IS NOT 'receipt'
        THEN RAISE(ABORT, 'batch must reference a receipt operation')
    END;
    SELECT CASE
        WHEN (SELECT is_archived FROM products WHERE id = NEW.product_id) IS NOT 0
        THEN RAISE(ABORT, 'cannot receive stock for an archived or missing product')
    END;
    SELECT CASE
        WHEN NEW.quantity_remaining <> 0
        THEN RAISE(ABORT, 'batch quantity must be initialized through a receipt movement')
    END;
    SELECT CASE
        WHEN (SELECT tracks_expiry FROM products WHERE id = NEW.product_id) = 1 AND NEW.expiry_date IS NULL
        THEN RAISE(ABORT, 'expiry date required for expiry-tracked product')
    END;
    SELECT CASE
        WHEN (SELECT tracks_expiry FROM products WHERE id = NEW.product_id) = 0 AND NEW.expiry_date IS NOT NULL
        THEN RAISE(ABORT, 'expiry date must be null for a product without expiry tracking')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_product_archive_requires_empty_stock
BEFORE UPDATE OF is_archived ON products
WHEN OLD.is_archived = 0 AND NEW.is_archived = 1
BEGIN
    SELECT CASE
        WHEN EXISTS (SELECT 1 FROM stock_batches WHERE product_id = OLD.id AND quantity_remaining > 0)
        THEN RAISE(ABORT, 'cannot archive a product with remaining stock')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_product_expiry_tracking_locked_after_batch
BEFORE UPDATE OF tracks_expiry ON products
WHEN OLD.tracks_expiry <> NEW.tracks_expiry
BEGIN
    SELECT CASE
        WHEN EXISTS (SELECT 1 FROM stock_batches WHERE product_id = OLD.id)
        THEN RAISE(ABORT, 'expiry tracking cannot change after a batch has been created')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_sales_requires_sale_operation
BEFORE INSERT ON sales
WHEN (SELECT operation_type FROM stock_operations WHERE id = NEW.operation_id) IS NOT 'sale'
BEGIN
    SELECT RAISE(ABORT, 'sale must reference a sale operation');
END;

CREATE TRIGGER IF NOT EXISTS trg_sale_item_requires_active_product
BEFORE INSERT ON sale_items
WHEN (SELECT is_archived FROM products WHERE id = NEW.product_id) IS NOT 0
BEGIN
    SELECT RAISE(ABORT, 'cannot sell an archived or missing product');
END;

CREATE TRIGGER IF NOT EXISTS trg_validate_stock_movement_insert
BEFORE INSERT ON stock_movements
BEGIN
    SELECT CASE
        WHEN (SELECT quantity_remaining FROM stock_batches WHERE id = NEW.batch_id) + NEW.quantity_delta < 0
        THEN RAISE(ABORT, 'insufficient batch inventory')
    END;
    SELECT CASE
        WHEN NEW.quantity_delta > 0
             AND (SELECT operation_type FROM stock_operations WHERE id = NEW.operation_id) NOT IN ('receipt', 'adjustment_in')
        THEN RAISE(ABORT, 'only receipt operations may increase stock')
    END;
    SELECT CASE
        WHEN (SELECT operation_type FROM stock_operations WHERE id = NEW.operation_id) = 'receipt'
             AND (
                 NEW.quantity_delta <= 0
                 OR NEW.sale_item_id IS NOT NULL
                 OR (SELECT receipt_operation_id FROM stock_batches WHERE id = NEW.batch_id) <> NEW.operation_id
                 OR NEW.quantity_delta <> (SELECT quantity_received FROM stock_batches WHERE id = NEW.batch_id)
             )
        THEN RAISE(ABORT, 'invalid receipt movement')
    END;
    SELECT CASE
        WHEN (SELECT operation_type FROM stock_operations WHERE id = NEW.operation_id) = 'sale'
             AND (
                 NEW.quantity_delta >= 0
                 OR NEW.sale_item_id IS NULL
                 OR NOT EXISTS (
                     SELECT 1
                     FROM sales s
                     JOIN sale_items si ON si.sale_id = s.id
                     WHERE s.operation_id = NEW.operation_id
                       AND si.id = NEW.sale_item_id
                       AND si.product_id = NEW.product_id
                 )
                 OR (
                     (SELECT tracks_expiry FROM products WHERE id = NEW.product_id) = 1
                     AND (SELECT expiry_date FROM stock_batches WHERE id = NEW.batch_id)
                         < (SELECT business_date FROM stock_operations WHERE id = NEW.operation_id)
                 )
             )
        THEN RAISE(ABORT, 'invalid sale movement')
    END;
    SELECT CASE
        WHEN (SELECT operation_type FROM stock_operations WHERE id = NEW.operation_id) = 'adjustment_in'
             AND (
                 NEW.quantity_delta <= 0
                 OR NEW.sale_item_id IS NOT NULL
                 OR (SELECT is_archived FROM products WHERE id = NEW.product_id) IS NOT 0
             )
        THEN RAISE(ABORT, 'invalid inbound stock adjustment')
    END;
    SELECT CASE
        WHEN (SELECT operation_type FROM stock_operations WHERE id = NEW.operation_id) IN ('disposal', 'adjustment_out')
             AND (NEW.quantity_delta >= 0 OR NEW.sale_item_id IS NOT NULL)
        THEN RAISE(ABORT, 'invalid stock removal movement')
    END;
END;

CREATE TRIGGER IF NOT EXISTS trg_update_batch_quantity_after_movement
AFTER INSERT ON stock_movements
BEGIN
    UPDATE stock_batches
    SET quantity_remaining = quantity_remaining + NEW.quantity_delta
    WHERE id = NEW.batch_id;
END;

CREATE TRIGGER IF NOT EXISTS trg_movements_are_immutable_update
BEFORE UPDATE ON stock_movements
BEGIN
    SELECT RAISE(ABORT, 'stock movements are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_movements_are_immutable_delete
BEFORE DELETE ON stock_movements
BEGIN
    SELECT RAISE(ABORT, 'stock movements are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_operations_are_immutable_update
BEFORE UPDATE ON stock_operations
BEGIN
    SELECT RAISE(ABORT, 'stock operations are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_operations_are_immutable_delete
BEFORE DELETE ON stock_operations
BEGIN
    SELECT RAISE(ABORT, 'stock operations are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_batches_metadata_immutable
BEFORE UPDATE OF product_id, receipt_operation_id, received_date, expiry_date, quantity_received, unit_cost ON stock_batches
BEGIN
    SELECT RAISE(ABORT, 'batch receipt details are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_sales_are_immutable_update
BEFORE UPDATE ON sales
BEGIN
    SELECT RAISE(ABORT, 'sales are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_sales_are_immutable_delete
BEFORE DELETE ON sales
BEGIN
    SELECT RAISE(ABORT, 'sales are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_sale_items_are_immutable_update
BEFORE UPDATE ON sale_items
BEGIN
    SELECT RAISE(ABORT, 'sale items are immutable');
END;
CREATE TRIGGER IF NOT EXISTS trg_sale_items_are_immutable_delete
BEFORE DELETE ON sale_items
BEGIN
    SELECT RAISE(ABORT, 'sale items are immutable');
END;

CREATE TABLE IF NOT EXISTS app_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    expiry_warning_days INTEGER NOT NULL DEFAULT 30 CHECK (expiry_warning_days >= 0),
    updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
INSERT OR IGNORE INTO app_settings (id, expiry_warning_days) VALUES (1, 30);

CREATE VIEW IF NOT EXISTS v_batch_balance_audit AS
SELECT
    b.id AS batch_id,
    b.product_id,
    b.quantity_received,
    b.quantity_remaining AS stored_quantity,
    COALESCE(SUM(m.quantity_delta), 0) AS ledger_quantity,
    b.quantity_remaining - COALESCE(SUM(m.quantity_delta), 0) AS difference,
    COALESCE(SUM(CASE WHEN op.operation_type = 'receipt' THEN m.quantity_delta ELSE 0 END), 0) AS ledger_received_quantity,
    b.quantity_received - COALESCE(SUM(CASE WHEN op.operation_type = 'receipt' THEN m.quantity_delta ELSE 0 END), 0) AS receipt_difference,
    COALESCE(SUM(CASE WHEN op.operation_type = 'receipt' THEN 1 ELSE 0 END), 0) AS receipt_movement_count
FROM stock_batches b
LEFT JOIN stock_movements m ON m.batch_id = b.id
LEFT JOIN stock_operations op ON op.id = m.operation_id
GROUP BY b.id, b.product_id, b.quantity_received, b.quantity_remaining;

CREATE VIEW IF NOT EXISTS v_sale_item_allocation_audit AS
SELECT
    si.id AS sale_item_id,
    si.quantity AS sold_quantity,
    COALESCE(SUM(CASE WHEN op.operation_type = 'sale' THEN -m.quantity_delta ELSE 0 END), 0) AS allocated_quantity,
    si.quantity - COALESCE(SUM(CASE WHEN op.operation_type = 'sale' THEN -m.quantity_delta ELSE 0 END), 0) AS difference
FROM sale_items si
LEFT JOIN stock_movements m ON m.sale_item_id = si.id
LEFT JOIN stock_operations op ON op.id = m.operation_id
GROUP BY si.id, si.quantity;

COMMIT;
