# WarungWise — Phase 5: Product Management

**Phase:** 5 — Product Management  
**Implementation scope:** Product catalogue, creation, editing, search, filtering, and safe archiving  
**Related documents:** [Project Brief](PROJECT_BRIEF.md) · [Requirements and User Flows](REQUIREMENTS_AND_USER_FLOWS.md) · [Database Design](DATABASE_DESIGN.md) · [Phase 4 Backend Foundation](PHASE_4_BACKEND_FOUNDATION.md)

## 1. Objective

Implement the first complete business workflow on top of the Phase 4 Flask and SQLite foundation. The local operator can maintain a product catalogue without paid services, external APIs, sample records, or a separate database server.

## 2. Implemented Features

- **Catalogue:** Lists active, archived, or all products. Search covers product name, SKU, and category. An optional exact category filter is provided.
- **Create:** Saves a product with its name, optional SKU and category, inventory unit, reference cost, selling price, minimum-stock threshold, restock lead time, safety stock, and expiry-tracking preference.
- **Edit:** Updates current product settings and the updated-at timestamp. Historical sale-line selling-price snapshots are not rewritten.
- **SKU integrity:** Trims and uppercases non-empty SKUs, checks duplicates without case sensitivity, uses parameterized SQL, and retains the database unique index as the final guard.
- **Safe archive:** Uses a POST form with session-bound CSRF validation. A product with any remaining quantity cannot be archived. Historical sales, batches, and movements are preserved; the product row is never deleted.
- **Expiry preference:** The form refuses to change a product expiry-tracking setting after any stock batch exists, matching the database rule.
- **User interface:** Adds catalogue navigation, responsive product forms and tables, field-level error messages, success/warning notifications, empty states, and an archive confirmation.

## 3. Validation Rules

| Field | Rule |
|---|---|
| Product name | Required; up to 120 characters after trimming |
| SKU | Optional; up to 50 characters; normalized to uppercase; unique without case sensitivity |
| Category | Optional; up to 80 characters after trimming |
| Inventory unit | Required; up to 30 characters after trimming |
| Reference cost | Integer IDR amount greater than or equal to zero |
| Selling price | Integer IDR amount greater than zero |
| Minimum stock | Non-negative whole number |
| Restock lead time | Whole number of at least one day |
| Safety stock | Non-negative whole number |
| Expiry tracking | Explicit yes/no choice; cannot change after a batch exists |

All critical validation runs on the server. SQL values are passed as parameters; the only dynamically assembled SQL fragments are fixed conditions chosen by application code. SQLite constraints and triggers remain authoritative safeguards.

## 4. Routes

| Method | Route | Purpose |
|---|---|---|
| GET | /products | List, search, and filter products |
| GET, POST | /products/new | Render and submit product creation form |
| GET, POST | /products/<product_id>/edit | Render and submit product edits |
| POST | /products/<product_id>/archive | Archive a product only when no quantity remains |

Mutating forms include a session-bound CSRF token. Archive operations use POST rather than a state-changing GET request. Unknown product IDs use the application's 404 page.

## 5. Explicitly Out of Scope

This milestone does not implement stock receipt, batch creation through the user interface, sales, disposal, stock adjustments, supplier records, authentication, multi-shop support, forecasting, CSV reports, or paid APIs. Product management does not manufacture inventory quantities: the catalogue displays remaining quantities only from existing batch records.

## 6. Verification

Run the test suite from the repository root after creating and activating the Python virtual environment and installing requirements.txt:

    python -m unittest discover -s tests -v

The expanded tests cover the existing Phase 4 smoke behavior and product catalogue setup, product creation and normalization, invalid values, case-insensitive SKU uniqueness, search and category filtering, editing, safe archiving, expiry-setting restrictions, and CSRF enforcement.

**Verification status:** All 20 tests passed in GitHub Actions on Python 3.12 ([run details](https://github.com/krisvan123/CS50X_FinalProject/actions/runs/39202850512)). The archive stock guard is also enforced by schema.sql; the application check provides a user-facing explanation before the database rejects an invalid update. Running the test command locally is still recommended.

## 7. Acceptance Checklist

- [x] Product list displays real database records and has active, archived, and all-status filters.
- [x] Search covers name, SKU, and category.
- [x] Create and edit forms validate critical fields server-side.
- [x] Empty and duplicate SKUs are handled according to the schema.
- [x] Prices are stored as integer IDR values.
- [x] Expiry-tracking preference cannot be changed after batch history exists.
- [x] Archive is POST-only, CSRF-protected, and blocked while stock remains.
- [x] Archive preserves the product and related historical records.
- [x] Tests and setup documentation are included.
- [x] GitHub Actions passed the full 20-test suite on Python 3.12.
- [ ] The same test suite has also been run on the developer's local workstation.
