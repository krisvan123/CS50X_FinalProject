# Phase 9 — Restock Recommendations

**Status:** Implemented and verified by [GitHub Actions on Python 3.12](https://github.com/krisvan123/CS50X_FinalProject/actions/runs/39208986771) — 43 automated tests passed.  
**Scope:** Explainable, rule-based product restock estimates using recent sales, lead time, safety stock, and sellable inventory.

## User workflow

The Restock advice item in the sidebar opens `/recommendations`. The page shows current summary counts, an observation window, the calculation, and a product-level table. The list can be searched by product name or SKU. It is read-only; it never creates a purchase order or changes stock quantities.

## Calculation

- The observation window covers the latest 30 calendar days, including today.
- Recent unit sales are summed from recorded sale items by each sale's business date.
- The observed history span begins on the first recorded sale date within that window and ends today, up to 30 days.
- At least 7 calendar days of observed sales history are required before a sales-based estimate is presented.
- Sellable stock includes only positive batch quantities received on or before today and not expired as of today. Expired quantities are excluded.
- Average daily sales = units sold during the observed period / number of observed calendar days.
- Target stock = ceiling((average daily sales × product lead time) + product safety stock).
- Suggested restock = max(0, target stock − current sellable stock).

## Insufficient-data safeguards

- Products without recorded sales history show that no estimate is available.
- Products with sales history but no recorded sale in the last 30 days are flagged as having no recent sales; the app withholds a suggested quantity.
- Products with fewer than 7 observed calendar days of sales history are marked as building history. The observed average may be shown for context, but the suggested quantity remains withheld.
- Only products with sufficient recent sales history contribute to the total suggested-unit summary.
- The recommendations are estimates, not forecasts or purchase orders. The calculation does not account for unreceived purchase orders, supplier minimums, cash constraints, seasonality, or promotions.

## Implementation

- Backend: `GET /recommendations` in `app.py`, parameterized SQLite queries and Python `math.ceil`.
- Interface: `templates/recommendations/index.html`.
- Navigation, presentation, and reduced-motion-safe decoration: `templates/base.html`, `static/css/styles.css`, and `static/js/app.js`.
- Tests cover no sales history, an exact recommendation calculation, and withholding estimates when only one day of sales is available.

## Review and verification

Run:

```powershell
python -m unittest discover -s tests -v
```

Verification on October 19, 2026: GitHub Actions ran all 43 automated tests successfully on Python 3.12, including tests for a calculated restock quantity, missing history, and less than 7 days of history. Also review a product with no recent sales and confirm expired stock is excluded and recommendations never change the inventory ledger.

## AI assistance note

ChatGPT assisted with the implementation and test drafting for this phase. The project author should review the SQL aggregation, date-window logic, minimum-history rule, and rounding formula and be able to explain them before the CS50x submission.
