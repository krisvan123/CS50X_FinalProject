# Phase 8 — Dashboard and Expiry Alerts

**Status:** Implemented; automated verification is pending the latest CI run.  
**Scope:** Dashboard summaries, low-stock watchlist, batch-level expiry watchlist, and visible interaction polish.

## What changed

- Added a low-stock watchlist derived from active products and their sellable batch quantities. Expired remaining stock is not counted as sellable inventory.
- Added an expiry watchlist showing batches with remaining stock that are already expired or fall within the configured expiry-warning window.
- Prioritised already-expired batches ahead of upcoming expiry dates and limited each watchlist to six actionable rows. The badge uses the dashboard's full counts, not only the visible rows.
- Kept figures database-backed. No demo values, external APIs, AI prediction, or unsupported business-impact claims were introduced.
- Redesigned the dashboard heading, status strip, metric cards, and watchlists with stronger visual hierarchy, gradients, responsive spacing, hover states, entrance reveals, and animated metric counts.
- Added reduced-motion handling. Motion affects presentation only; all stock calculations and validations remain server-side.
- Added a dashboard test for a low-stock product with an approaching expiry date.

## Business rules

- Sellable quantity for the low-stock watchlist includes only positive remaining quantities from batches that are not expired on the current business date.
- Low stock means sellable quantity is less than or equal to the product's configured minimum stock.
- Expiry warnings use the `expiry_warning_days` setting from `app_settings`.
- Expired stock remains visible in the expiry watchlist when its remaining quantity is above zero, but it is excluded from sellable quantity.
- The watchlists are summaries, not stock-changing workflows. The append-only movement ledger remains the audit trail for changes.

## Review and verification

Run the test suite from the repository root:

```powershell
python -m unittest discover -s tests -v
```

Also open the dashboard at desktop and mobile widths, verify the watchlists with empty and populated databases, and confirm animation respects the operating system's reduced-motion preference. This document should be updated with the observed CI result after the workflow completes.

## AI assistance note

ChatGPT assisted with the implementation and test drafting for this phase. The project author should review the changes, run the tests, and be able to explain the database queries, business rules, and JavaScript presentation behavior before submission.
