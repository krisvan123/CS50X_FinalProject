# WarungWise — Requirements and User Flows

**Phase:** 2 — Requirements and User Flows  
**Status:** Design specification; implementation has not started  
**Related document:** [Project Brief and Scope](PROJECT_BRIEF.md)

## 1. Purpose

This document translates the Phase 1 scope into functional requirements, user workflows, validation rules, failure behavior, and acceptance scenarios. It will guide the database design and implementation without prematurely prescribing every table or function.

The initial application is a local, single-shop, single-user web application. Its interface will be in Indonesian, with prices represented in Indonesian rupiah (IDR). All business-critical validation must take place on the server; browser-side validation and JavaScript may improve usability but cannot be the only validation layer.

## 2. Actors and Operating Assumptions

### Primary actor

**Shop operator:** the owner or staff member who maintains product records, receives stock, records sales, checks expiry status, records disposal, and reviews reports.

### Operating assumptions

- The first release is used locally by one operator and does not include authentication or role-based permissions.
- Product and transaction records are stored in a local SQLite database.
- Dates are interpreted using the local machine's calendar date. Date handling must be consistent across the application.
- Quantities are whole units for the initial release. Fractional units and unit conversions are out of scope.
- Each product has one defined inventory unit, such as bottle, pack, or piece.
- Stock is represented at batch level. Batch records are the source for calculating remaining inventory.
- Database write operations must be atomic where multiple records form a single business operation.
- The core workflows must not depend on paid APIs or external network services.

## 3. User Stories and Priorities

| ID | User story | Priority |
|---|---|---|
| US-01 | As a shop operator, I want to create and maintain product records so that my catalogue is accurate. | MVP |
| US-02 | As a shop operator, I want to search and filter products so that I can find an item quickly. | MVP |
| US-03 | As a shop operator, I want to receive stock into a dated batch so that quantities and expiry information are traceable. | MVP |
| US-04 | As a shop operator, I want to record a sale so that eligible stock is reduced and the sale is recorded. | MVP |
| US-05 | As a shop operator, I want stock changes to have a reason and history so that inventory changes can be audited. | MVP |
| US-06 | As a shop operator, I want to identify low-stock, near-expiry, and expired inventory so that I can act before avoidable problems occur. | MVP |
| US-07 | As a shop operator, I want to record damaged or expired stock disposal so that sellable quantities and recorded losses remain accurate. | MVP |
| US-08 | As a shop operator, I want a dashboard based on saved records so that I can understand current inventory conditions. | Final target |
| US-09 | As a shop operator, I want an explainable restock recommendation so that I can estimate future needs from recorded sales. | Final target |
| US-10 | As a shop operator, I want date-filtered reports and CSV exports so that I can review or retain records outside the application. | Final target |

## 4. Functional Requirements

### 4.1 Product Management

- **FR-PROD-01:** The operator can create, view, edit, search, filter, and archive products.
- **FR-PROD-02:** A product includes a name, optional SKU, optional category, inventory unit, cost price, selling price, minimum-stock threshold, restock lead time in days, and safety-stock quantity.
- **FR-PROD-03:** Products can be configured to track expiry or not. This setting determines whether a batch expiry date is required and whether expiry alerts apply. The final representation will be formalized during Phase 3.
- **FR-PROD-04:** A non-empty SKU must be unique without regard to letter case.
- **FR-PROD-05:** Archiving preserves all historical sales and stock movements. A product with any batch quantity remaining cannot be archived until that quantity has been properly sold, adjusted, or disposed of.
- **FR-PROD-06:** Archived products cannot be selected for new stock receipts or sales. Their historical data remains available to relevant reports.

### 4.2 Stock Receipt and Batch Tracking

- **FR-BATCH-01:** The operator can receive stock for an active product using a positive whole-number quantity.
- **FR-BATCH-02:** Each receipt creates a traceable batch or receipt record with product, quantity received, receipt date, remaining quantity, and applicable unit cost.
- **FR-BATCH-03:** For a product configured to track expiry, an expiry date is required. It must be a valid calendar date and cannot be earlier than the receipt date.
- **FR-BATCH-04:** For products not configured to track expiry, the application must not invent an expiry date. The interface identifies expiry status as not tracked or not applicable.
- **FR-BATCH-05:** A successful receipt updates inventory and records its stock movement in the same database transaction.
- **FR-BATCH-06:** Receiving stock again creates a traceable receipt or batch entry rather than silently overwriting an earlier batch's date or history.

### 4.3 Sales

- **FR-SALE-01:** The operator can record one sale containing one or more product lines, each with a product and a positive whole-number quantity.
- **FR-SALE-02:** Only active products and eligible, sellable batch quantities may satisfy a sale.
- **FR-SALE-03:** For expiry-tracked products, stock is allocated using First Expired, First Out (FEFO): the earliest non-expired batch is consumed first, with receipt date used to break ties.
- **FR-SALE-04:** Each sale line stores the unit selling price used at the time of sale so later product price changes do not rewrite historical revenue.
- **FR-SALE-05:** The application rejects a sale if any line has invalid input or insufficient sellable stock. No part of the sale may be committed.
- **FR-SALE-06:** A successful sale records its timestamp, line items, quantity, sale-price snapshot, and associated stock movements. A sale may consume multiple batches if an earlier eligible batch does not contain enough stock.
- **FR-SALE-07:** Repeated submission of the same completed inventory operation must not create a second stock change. A server-side duplicate-submission safeguard is required; disabling a browser button alone is insufficient.
- **FR-SALE-08:** Sales returns and refunds are out of scope for the initial release and must not be simulated as ordinary sales or unexplained stock adjustments.

### 4.4 Stock Adjustments and Disposal

- **FR-STOCK-01:** The operator can record a batch-level quantity correction in either direction when a documented stock-count discrepancy is identified; each correction must reference an existing batch and include a reason.
- **FR-STOCK-02:** A stock correction requires a positive whole-number absolute quantity, a selected batch, a reason, a timestamp, and an optional note. Its operation type determines whether the quantity is added or removed.
- **FR-STOCK-03:** A removal cannot exceed the batch's remaining quantity. A positive correction applies only to an existing batch and records a reason; it does not create a new receipt batch.
- **FR-STOCK-04:** Disposal of damaged or expired goods reduces remaining inventory and creates a stock-movement record atomically.
- **FR-STOCK-05:** The recorded value of disposed goods uses the disposed quantity and applicable batch cost. An expiry warning alone is not a realized disposal loss.
- **FR-STOCK-06:** New deliveries must use the stock-receipt workflow so a new batch and its cost are recorded. A positive adjustment is allowed only to correct a documented count discrepancy on an existing batch and must include a reason; it cannot be used as an unexplained way to enter a new delivery.
- **FR-STOCK-07:** A stock operation cannot leave a batch with a negative remaining quantity.

### 4.5 Inventory Status and Expiry Alerts

- **FR-ALERT-01:** The application distinguishes low-stock products, batches nearing expiry, and expired batches with remaining quantity.
- **FR-ALERT-02:** Sellable quantity is calculated from eligible batches and excludes expired or disposed stock.
- **FR-ALERT-03:** A product is low-stock when its sellable quantity is less than or equal to its configured minimum-stock threshold.
- **FR-ALERT-04:** The default expiry-warning window is 30 days and must be configurable through a simple application setting. Storage of this setting will be finalized during Phase 3.
- **FR-ALERT-05:** An approaching-expiry alert applies when an expiry-tracked batch has a remaining quantity greater than zero and its expiry date falls within the configured warning window, including the current date.
- **FR-ALERT-06:** An expired alert applies when a batch has a remaining quantity greater than zero and its expiry date is earlier than the current date.
- **FR-ALERT-07:** Status must be conveyed with text as well as visual styling; color alone is insufficient.
- **FR-ALERT-08:** Counts must be labelled as product counts or batch counts. Several affected batches belonging to one product must not create ambiguous totals.

### 4.6 Dashboard, Restock Recommendations, Reports, and CSV

These are final-target features and will be implemented only after the MVP is stable.

- **FR-REP-01:** Dashboard metrics must be derived from saved records, not hard-coded totals.
- **FR-REP-02:** Sales revenue is calculated from saved sale-line quantities and sale-price snapshots for the selected period.
- **FR-REP-03:** Recorded disposal value is calculated from disposal records and their applicable costs. Expiry warnings alone do not count as realized disposal loss.
- **FR-REP-04:** Restock recommendations use average daily sales, configured lead time, safety stock, and current sellable quantity.
- **FR-REP-05:** The initial calculation is: target stock = (average daily sales × lead-time days) + safety stock; suggested restock = max(0, target stock − sellable stock).
- **FR-REP-06:** The observation period and minimum sales-history requirement must be documented. If history is insufficient, the interface must say that the recommendation is unavailable or based on limited data.
- **FR-REP-07:** Reports can filter transactions by a defined date range. Additional filters will be included only if they can be implemented and tested accurately.
- **FR-REP-08:** CSV export must reflect the active report filters and use a consistent, documented column structure.
- **FR-REP-09:** CSV output must correctly handle delimiters, quoted text, and values, and must not present a partial or failed export as successful.

## 5. Cross-Cutting Validation Rules

The server must validate every submitted value regardless of client-side checks.

| Field or operation | Validation requirement | Failure behavior |
|---|---|---|
| Product name | Required after trimming whitespace; non-empty | Reject save and identify the missing field |
| SKU | Optional; trim whitespace; reject duplicate non-empty SKU without case sensitivity | Explain the conflict without exposing database errors |
| Category | Optional text; normalize whitespace and enforce a documented length limit | Explain invalid input |
| Inventory unit | Required and non-empty | Reject missing or invalid unit |
| Cost price | Numeric value greater than or equal to zero | Reject negative, malformed, or non-finite values |
| Selling price | Numeric value greater than zero | Reject zero, negative, malformed, or non-finite values |
| Minimum stock | Whole number greater than or equal to zero | Reject negative or fractional values |
| Lead time | Whole number of at least one day | Reject zero, negative, or fractional values |
| Safety stock | Whole number greater than or equal to zero | Reject negative or fractional values |
| Receipt quantity | Positive whole number | Reject zero, negative, fractional, or malformed values |
| Expiry date | Required for expiry-tracked products; valid date not earlier than receipt date | Reject invalid dates with a clear message |
| Sale line | Active product, positive whole quantity, sufficient eligible stock | Reject the entire sale without committing any line |
| Disposal quantity | Positive whole quantity no greater than selected batch's remaining quantity | Reject without modifying the batch |
| Date filter | Valid dates; start date cannot be after end date | Explain the invalid date range |
| Archive | No batch may have remaining quantity | Preserve the product and explain the condition to resolve |

Numeric values must be parsed and validated before database writes. Database access must use parameterized SQL. User-facing errors must not expose SQL statements, file paths, stack traces, or sensitive configuration values.

## 6. User Flows

### Flow A — Open the Dashboard

**Goal:** Understand current inventory conditions.

1. The operator opens the application.
2. The server loads inventory summaries and current alerts from the database.
3. The page displays product counts, low-stock status, expiry alerts, and transaction summaries when available.
4. The operator selects a product, batch, or report to investigate an alert.

**Inputs:** None required; the date range or expiry-warning setting may be optional.  
**Expected result:** Metrics reflect database state, with informative empty states if no records exist.  
**Failure cases:** Database unavailable, query failure, no products, or no transactions.  
**Recovery:** Show an understandable error or empty state. Do not replace failed queries with hard-coded business figures.

### Flow B — Create or Edit a Product

**Goal:** Maintain correct product and restock settings.

1. The operator opens the product list and selects Add Product or Edit.
2. The operator enters product name, optional SKU and category, unit, cost, selling price, minimum-stock threshold, lead time, safety stock, and expiry-tracking preference.
3. The server validates the submitted values.
4. If valid, the server saves the product and displays confirmation.
5. If invalid, the form is redisplayed with an explanation and safe preservation of other entered values where practical.

**Expected result:** A valid product appears in the list and can be found through search or filters.  
**Failure cases:** Missing name or unit, invalid price, duplicate SKU, invalid quantities, or product not found.  
**Integrity rule:** Editing current prices or settings must not silently change historical sale-price snapshots or previous batch-cost records.

### Flow C — Receive Stock

**Goal:** Add inventory while preserving batch-level traceability.

1. The operator selects an active product and opens Receive Stock.
2. The operator enters quantity, receipt date, batch unit cost, and expiry date when required.
3. The server validates product status, quantity, dates, and cost.
4. In one database transaction, the application records the batch or receipt and its stock movement.
5. The operator sees the resulting batch and updated inventory.

**Inputs:** Product, positive whole quantity, receipt date, unit cost, and applicable expiry date.  
**Expected result:** Sellable stock increases by the received quantity and the receipt appears in stock history.  
**Failure cases:** Archived or missing product, invalid quantity/date/cost, expiry earlier than receipt date, or database failure.  
**Integrity rule:** If any part of the receipt transaction fails, neither the stock increase nor the movement record may be committed.

### Flow D — Record a Sale

**Goal:** Record a sale without overselling or losing traceability.

1. The operator opens Record Sale and adds one or more product lines.
2. For each line, the operator chooses an active product and enters a positive whole quantity.
3. The server checks every line against available sellable stock.
4. For expiry-tracked products, stock is allocated from eligible batches using FEFO.
5. If every line passes validation, the application atomically saves the sale, sale lines, and batch-level movements. Sale prices are saved as historical snapshots.
6. The operator sees the sale summary, calculated revenue, and updated inventory.

**Expected result:** Sale lines are recorded, eligible batch quantities are reduced, and movement history agrees with the resulting stock.  
**Failure cases:** Insufficient sellable stock, archived product, invalid quantity, expired-only stock, duplicate submission, or database failure.  
**Integrity rule:** If any sale line fails, the entire sale is rejected and no line changes stock. A retry of a completed request must not create a duplicate sale.

### Flow E — Review Stock and Expiry Status

**Goal:** Identify inventory that needs action.

1. The operator opens the inventory or expiry view.
2. The application calculates remaining quantities and compares batch expiry dates with the current date and warning window.
3. The operator filters by low-stock, approaching-expiry, or expired status.
4. The operator opens a product or batch to inspect quantity, dates, and movements.

**Expected result:** Status text and quantities are consistent with batch records.  
**Failure cases:** Missing expiry date, no products, no matching batches, or query failure.  
**Integrity rule:** Batches for products without expiry tracking are labelled accordingly, never assigned a made-up date, and excluded from date-based expiry calculations.

### Flow F — Dispose of Damaged or Expired Stock

**Goal:** Remove unsellable inventory with a traceable reason.

1. The operator selects a batch and opens Record Disposal/Adjustment.
2. The operator selects a reason, enters a positive quantity to remove, and may enter a note.
3. The server checks that the batch exists and that the quantity does not exceed its remaining amount.
4. The application atomically reduces batch quantity and records the movement and applicable cost basis.
5. The operator sees the updated batch, stock level, and recorded disposal value.

**Expected result:** Remaining quantity decreases by exactly the entered amount, and the event appears in history.  
**Failure cases:** Missing reason, zero or excessive quantity, invalid batch, or database failure.  
**Integrity rule:** A failed operation must not alter stock. Disposal value is recorded only for goods actually disposed of.

### Additional Flow — Correct a Stock Count (Positive Adjustment)

**Goal:** Record a justified count correction for an existing batch without rewriting its history.

1. The operator selects an existing batch and opens Stock Count Correction.
2. The operator enters a positive whole-number adjustment quantity and a required reason explaining the discrepancy.
3. The server confirms the product and batch exist, the product is active, and the submitted values are valid.
4. In one database transaction, the application creates an adjustment operation and a positive movement linked to the existing batch.
5. The operator sees the updated quantity and the new movement in the batch history.

**Expected result:** The batch balance changes by the stated quantity and the reason remains auditable.  
**Failure cases:** Missing reason, invalid quantity, archived product, invalid batch, or database error.  
**Integrity rule:** This workflow corrects an existing batch count only. A new delivery must be received through the stock-receipt workflow and create a new batch.

### Flow G — Archive a Product

**Goal:** Retire a product without erasing history.

1. The operator selects Archive for an active product.
2. The server checks that no batch for the product has remaining quantity.
3. The operator confirms the action.
4. The product becomes inactive and is omitted from new sales and receipts, while historical records remain accessible.

**Expected result:** The product is unavailable for new operations but remains traceable in history and relevant reports.  
**Failure cases:** Remaining stock, missing product, or database failure.  
**Integrity rule:** Archiving never cascades into deletion of transaction history.

### Flow H — Review Restock Recommendations (Final Target)

**Goal:** Estimate the quantity that may need replenishment.

1. The operator opens the restock view.
2. The server retrieves sales history for the documented observation period, lead time, safety stock, and sellable quantity.
3. The application computes target stock and suggested restock quantity.
4. The result displays the calculation inputs and an explanation of the formula.
5. If sales history is insufficient, the application displays a limitation notice instead of presenting the result as dependable.

**Expected result:** The recommendation can be reproduced from the displayed inputs and documented formula.  
**Failure cases:** Insufficient sales history, invalid configuration, zero stock, or query failure.  
**Integrity rule:** Recommendations are advisory and do not create purchase orders or alter stock.

### Flow I — Review Reports and Export CSV (Final Target)

**Goal:** Review recorded business activity outside the dashboard.

1. The operator opens Reports and selects a valid date range.
2. The application queries sales and stock movement records that match the selected range.
3. The operator reviews totals and available product or category breakdowns.
4. The operator exports the current report to CSV.
5. The exported file uses the same filters and column definitions as the on-screen report.

**Expected result:** Report totals can be reconciled with database records for the selected period.  
**Failure cases:** Invalid date range, no matching rows, database failure, or export error.  
**Recovery:** Empty reports display a helpful message. Export errors are reported instead of presenting an incomplete file as successful.

## 7. Global Error Handling and Interaction Requirements

- Mutating operations use server-side validation and database transactions wherever multiple records must remain consistent.
- Successful POST operations redirect to a result or list view to reduce accidental browser resubmission. A server-side duplicate-operation safeguard is still required for inventory-changing actions.
- Error messages use plain language and identify what the user can correct without exposing technical internals.
- Forms preserve safe, non-sensitive values after validation failures where practical.
- Important destructive or irreversible actions require confirmation.
- Status is communicated through text and accessible labels, not color alone.
- Empty lists provide an explanation and, where appropriate, a next action.
- The single-user local assumption must be explicit. Development server and debug mode must not be presented as safe for public deployment.
- Application dates and expiry boundaries use one documented convention consistently.
- Archived products and historical movements remain referentially consistent.

## 8. Acceptance Scenarios

These scenarios define future test cases. They are test plans, not claims that tests have already been executed.

| ID | Given | When | Then |
|---|---|---|---|
| AT-01 | A valid new product form | The operator submits it | The product is saved and appears in the list |
| AT-02 | A product has an existing SKU | Another product uses the same SKU with different letter case | The second save is rejected with a clear message |
| AT-03 | An active product and valid receipt data | The operator receives stock | Batch quantity and movement history increase consistently |
| AT-04 | A product is configured to track expiry | A receipt is submitted without an expiry date | The receipt is rejected |
| AT-05 | An eligible batch has enough sellable stock | The operator records a valid sale | The sale is saved and stock falls by the sold quantity |
| AT-06 | A sale has multiple lines and at least one line lacks stock | The operator submits the sale | The entire transaction is rejected and no line changes stock |
| AT-07 | Two eligible batches have different expiry dates | A sale requires stock from both | The earlier-expiring eligible batch is consumed first |
| AT-08 | A batch has passed its expiry date | The operator attempts to sell from it | The expired quantity cannot satisfy the sale |
| AT-09 | A batch has five units remaining | The operator attempts to dispose of six | The operation is rejected and the quantity remains five |
| AT-10 | A product has a batch with remaining quantity | The operator tries to archive the product | Archiving is blocked and history remains unchanged |
| AT-11 | A product has insufficient sales history | The operator opens restock recommendations | The application explains the recommendation is unavailable or limited |
| AT-12 | A report is filtered to a date range | The operator exports CSV | The export contains only the filtered records and consistent totals |
| AT-13 | A database operation fails during a stock-changing transaction | The operation is rolled back | Neither the stock change nor its associated record is partially committed |
| AT-14 | There are no products or no matching report rows | The operator opens the relevant view | The UI shows a useful empty state rather than invented totals |

## 9. Decisions to Resolve During Phase 3 — Database Design

Phase 3 must translate these requirements into a consistent, traceable data model. It should explicitly evaluate:

- Products and their inventory/restock settings.
- Stock batches and batch-level remaining quantities, expiry dates, and cost basis.
- Stock movements with type, quantity, timestamp, reason, and source reference.
- Sale transaction headers and one or more sale lines, including historical selling-price snapshots.
- A reliable way to link sales, receipts, disposal events, and batch-level movements.
- Duplicate-submission protection for stock-changing operations.
- Application settings such as the expiry-warning window.
- Foreign-key rules, CHECK constraints, unique SKU behavior, indexes where justified, and transaction boundaries.

The final schema is not assumed in this document. Each table and relationship must serve a documented requirement and be reviewed before implementation.

## 10. Definition of Done for Phase 2

Phase 2 is documented when:

- Core user flows include inputs, expected outcomes, validation, and failure behavior.
- MVP and final-target requirements are clearly distinguished.
- Inventory, expiry, disposal, and sales integrity rules are explicit.
- Acceptance scenarios can be converted into automated or manual tests.
- Open database-design decisions are identified for Phase 3.

No implementation or test results are claimed in this document.
