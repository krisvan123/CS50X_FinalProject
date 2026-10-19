# WarungWise — Technical Design

## 1. Purpose and scope

WarungWise is a local-first inventory application for a single small shop. Its central engineering problem is maintaining a trustworthy relationship between a product's current quantity and the events that explain how that quantity was received, sold, discarded, or corrected. The design prioritizes traceable records, explicit rules, and testable behavior over integrations or predictive features.

The current release is intentionally single-operator and local. User accounts, authorization roles, multi-shop support, cloud synchronization, supplier purchasing orders, payments, refunds, and machine-learning forecasting are out of scope. The application should not be exposed to the public internet without a separate deployment and threat-model review.

## 2. Architecture

The application uses Flask for routing and request handling, Jinja templates for server-rendered pages, CSS for the interface, and a small JavaScript file for presentation effects and a live sale total preview. SQLite stores business records locally. Inventory logic does not depend on a paid API or a separate database server.

- `app.py` creates the Flask application and defines routes, form validation, stock workflows, sale allocation, reports, CSV exports, settings, and the health check.
- `database.py` creates a request-scoped SQLite connection, enables foreign keys on each connection, sets a row factory, and closes connections during Flask teardown.
- `schema.sql` declares tables, constraints, indexes, triggers, and audit views.
- `init_db.py` initializes only a new database, then runs SQLite integrity and foreign-key checks. It deliberately refuses to replace an existing database.
- `templates/` holds the shared layout and application pages. `static/css/styles.css` defines interface and responsive behavior; `static/js/app.js` adds presentation effects and a live sale-total preview.
- `tests/test_app.py` exercises routes and database behavior using temporary SQLite databases. GitHub Actions runs the suite on Python 3.12.

## 3. Data model

### Products

The `products` table stores the catalogue, SKU, category, unit, reference prices, minimum-stock threshold, lead time, safety stock, expiry-tracking preference, and archive flag. A non-empty SKU is unique case-insensitively. Archiving preserves historical records and is blocked when a batch still has remaining stock.

### Operations, batches, and movements

`stock_operations` records operation type, request token, UTC timestamp, business date, reason, and optional note. It groups all inventory effects from one user action. `stock_batches` stores one receipt lot, including received date, expiry date, original quantity, remaining quantity, and actual unit cost. `stock_movements` stores signed quantity changes that explain how each batch balance changed.

A database trigger adjusts `stock_batches.quantity_remaining` when a movement is inserted. Other constraints and triggers check movement direction, prevent negative balances, validate receipt/sale links, preserve movement history, and prevent expiry-tracked stock from being sold after expiry. The `v_batch_balance_audit` view compares stored balance with the movement ledger; `v_sale_item_allocation_audit` compares each sale-line quantity with its allocated batch quantity.

### Sales and sale items

`sales` references one sale operation; `sale_items` stores the product quantity and unit selling price captured when the sale was recorded. The current interface intentionally records one product line per sale transaction. That quantity may be fulfilled by several batches. This is a scope decision, not a claim that multi-item checkout is implemented.

Prices and costs are stored as whole Indonesian rupiah (IDR) values to avoid floating-point money arithmetic.

### Settings

The `app_settings` singleton stores the expiry-warning window. Its default is 30 days; Workspace settings permits whole-number values from zero to 365 days.

## 4. Inventory workflows and invariants

### Stock receipt

A receipt validates an active product, positive whole-number quantity, unit cost, received date, and expiry rules. It inserts a receipt operation and a new batch whose remaining quantity starts at zero, then inserts a positive receipt movement. A database trigger updates the balance from that movement. These writes commit together; on failure the transaction rolls back.

### Sale and FEFO

The sale route verifies an active product, positive quantity, a business date that is not in the future, and enough eligible inventory. Candidate batches must have been received by the sale's business date and must not have expired on that date. Allocation places dated batches first in earliest-expiry order, then receipt-date and batch-ID order; batches without expiry dates follow dated batches and use FIFO ordering.

Because the interface supports backdated sales, current stock alone is insufficient to validate an older transaction. The helper `_historical_sellable_capacity` replays each batch's movements in business-date and timestamp order. The route only counts quantities that are available on the requested date and will not cause any later recorded batch balance to become negative. The operation, sale item, and allocated movements are committed atomically.

### Disposal and stock-count correction

The Waste & corrections page supports disposal, inbound physical-count correction, and outbound physical-count correction against an existing batch. Every action requires a reason. New deliveries must use the receipt workflow so their new batch and unit cost are captured. Disposal and count-correction actions are dated today in the local application to avoid retroactive edits through the current UI. The operation and movement are written in one transaction, and the database trigger updates the batch balance.

Recorded disposal value is calculated as absolute disposal quantity multiplied by the affected batch's stored unit cost. It is not estimated loss based only on expiry status, and it is not net profit. Count corrections are not categorized as disposals.

### Duplicate-submission protection

A high-entropy request token is created when a stock-changing form is rendered, sent as a hidden field, and stored under a unique database constraint on the operation. Reposting that same rendered form token is recognized as an operation already processed and must not create a second receipt, sale, or stock action. This server-side protection complements rather than replaces CSRF validation.

## 5. Reporting and restock rules

The Reports page filters sales and stock movements by business date over a validated period of no more than 366 days. Gross revenue is quantity multiplied by the saved selling-price snapshot. The inventory report is a current snapshot; it does not reconstruct stock as of the selected historical dates. CSV export provides detailed sale lines, movement records, and a current batch inventory snapshot. Text fields are sanitized against common spreadsheet formula-leading characters.

Restock advice uses up to 30 calendar days of recorded sales. If no recent sales exist or the observed sales-history span is shorter than seven calendar days, the application withholds the quantitative estimate. Otherwise:

- Average daily sales = observed units sold divided by observed calendar days.
- Target stock = ceiling(average daily sales × lead time days + safety stock).
- Suggested restock = maximum of zero and target stock minus current sellable stock.

This is transparent decision support, not a guarantee or purchase order. The calculation does not account for unrecorded sales, supplier constraints, promotions, seasonality, or cash availability.

## 6. Security and failure handling

State-changing forms use a session-bound CSRF token. Receipts, sales, and stock actions also use operation-specific request tokens for duplicate protection. SQL uses parameter binding for user values; validation occurs on the server regardless of browser-side constraints. Jinja autoescaping applies to template values. CSV exports guard formula-leading text, use a UTF-8 BOM, set attachment headers, and are marked no-store.

The request body size is limited, and session cookies are configured HttpOnly and SameSite=Lax. The app reads a stable secret from `WARUNGWISE_SECRET_KEY` when set; otherwise it generates a random local-process secret. The latter is suitable for local development but can invalidate sessions after a restart. Authentication, authorization, HTTPS, production server configuration, stable deployed secret management, and public deployment are not claimed for this release.

## 7. Verification and limitations

The integrated automated suite contains 58 tests and passed on Python 3.12 in [GitHub Actions run 39213601559](https://github.com/krisvan123/CS50X_FinalProject/actions/runs/39213601559). Tests cover form validation, FEFO, expired stock, reports/CSV, disposal/count corrections, settings, duplicate request-token submissions, and a historical-balance scenario.

This CI result does not replace the Phase 12 manual browser and security gate. That phase must still cover real concurrent duplicate POSTs, broader temporal-ledger cases, keyboard/mobile/reduced-motion review, error paths, and the local setup flow. The README's Video Demo URL remains pending until the project video is recorded.
