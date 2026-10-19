# Phase 7 — Sales Recording and FEFO Allocation

## Goal

Allow a shop worker to record a sale against current product pricing while reducing inventory through the stock movement ledger. Stock is allocated by FEFO (First Expiry, First Out), using the earliest eligible expiry date first.

## Features

- Sales history with product search, captured unit prices, transaction dates, quantities, and gross totals.
- Sale form with active products, business date, quantity, and optional note. Each recorded transaction intentionally contains one product line; a single line can consume multiple eligible batches.
- Live sale preview showing the selected product's current availability, selling price, and estimated gross total.
- FEFO allocation across multiple batches when a sale quantity is larger than one batch.
- Excludes expired batches and batches that had not yet been received on the chosen business date.
- Captures the unit selling price on the sale item, preserving historical transaction value after the product price changes.
- Records the sale operation, sale, sale item, and all batch-level stock movements in one transaction.
- Adds a responsive Sales workspace and subtle UI motion with reduced-motion support.

## Inventory integrity

The route checks sellable quantity before creating any transaction records. It then inserts the sale operation and item, allocates eligible batches by expiry date and receipt date, and inserts negative stock movements. Existing SQLite triggers reject negative batch balances and expired stock allocation. If an integrity or database error occurs, the transaction is rolled back and no partial sale is committed.

## Scope boundary

The workflow currently records one product line per sale transaction. Multi-item checkout, payment processing, tax calculation, refunds, cost-of-goods-sold reporting, and stock disposal/adjustment are outside this phase. Gross sales must not be interpreted as profit.

## Local verification

Run from the project root:

\`\`\`powershell
python -m unittest discover -s tests -v
\`\`\`

For an existing initialized database, no schema rebuild is needed for this phase; the required tables were created in Phase 4. Keep local database files out of version control.
