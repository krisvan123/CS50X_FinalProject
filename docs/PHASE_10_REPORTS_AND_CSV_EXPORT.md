# Phase 10 — Reports and CSV Export

**Status:** Implementation committed; the latest automated test run is pending.  
**Scope:** Date-filtered sales analytics, daily revenue visualisation, top-product analysis, a current batch snapshot, and CSV downloads.

## Reports page

Open `/reports` from the sidebar. The default period is the last 30 calendar days, ending today. Users can select a different range of up to 366 calendar days. Start and end dates must be valid, cannot be in the future, and must be in chronological order.

The page displays:
- Gross revenue calculated from sale quantity multiplied by the selling-price snapshot saved with each sale.
- Transaction count and units sold for the selected business-date period.
- A daily revenue chart that includes zero-sales dates, the ten highest-revenue products, and recent stock movements in the selected period.
- A current inventory snapshot with sellable units, remaining batches, near-expiry batches, and expired batches.

The current inventory snapshot is explicitly separate from the selected historical reporting period. The application does not reconstruct historical batch balances. Gross revenue is not profit. A disposal/loss report will only be meaningful once a supported disposal workflow records those operations; the report page does not claim to calculate unrecorded loss.

## CSV downloads

Three exports are available:
- `/reports/export/sales?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`: all detailed sale lines in the selected period, with saved prices and gross totals.
- `/reports/export/movements?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`: the full movement ledger for the selected period, including operation, batch, signed quantity change, reason, and note.
- `/reports/export/inventory`: a current, non-depleted batch snapshot with receipt/expiry dates, remaining quantity, unit cost, and calculated status.

The on-page tables are previews, not the export limit. CSV exports include the full filtered result set and require no paid package or external API. CSV text fields are guarded against spreadsheet formula interpretation and the files use a UTF-8 BOM for spreadsheet compatibility.

## Technical implementation

- Flask reporting routes: `GET /reports` and `GET /reports/export/<report_type>` in `app.py`.
- Shared read-only query helpers for sales lines, movement records, and inventory batches.
- Parameterized SQL and strict date validation; export requests do not mutate inventory.
- Reports interface: `templates/reports/index.html`.
- Responsive styling and staged UI motion: `static/css/styles.css`, `static/js/app.js`, and the shared navigation in `templates/base.html`.

## Verification

Run the complete suite:

```powershell
python -m unittest discover -s tests -v
```

Tests cover empty reports, date-filtered revenue and daily trend, selected-period CSV exports, the movement ledger, formula-like product names/SKUs, invalid date ranges, and unsupported export types. Confirm the latest GitHub Actions run before treating this phase as verified.

## AI assistance note

ChatGPT assisted with the implementation, interface, and test drafting for this phase. The project author should review the query logic, date constraints, CSV safety rules, and what the reports do not calculate, and be able to explain them before submission.
