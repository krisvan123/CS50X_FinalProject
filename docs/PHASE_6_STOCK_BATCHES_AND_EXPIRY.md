# Phase 6 — Stock Batch and Expiry Management

## Goal

Implement stock intake by batch, with separate delivery dates, expiry dates, received quantities, and unit acquisition costs. Product-level stock totals are derived from batch records and movements rather than overwritten directly.

## Features

- Searchable stock-batch register with available, near-expiry, expired, and depleted filters.
- Batch-level received date, expiry date according to product configuration, quantity received, and unit acquisition cost.
- Receipt workflow that writes the stock operation, batch record, and positive movement in one SQLite transaction.
- Read-only stock movement ledger with search and movement-type filters.
- Server-side validation for active products, dates, positive whole-number quantities, non-negative whole-number costs, note length, and CSRF tokens.
- Dashboard and navigation entry points for receiving stock and reviewing history.
- Refined type hierarchy, form styling, tables, and responsive layouts using DM Sans and Manrope with local fallbacks.

## Inventory integrity

A new batch starts with \`quantity_remaining = 0\`. The associated receipt movement initializes the balance through the existing database trigger. A database failure rolls the transaction back; the application never silently overwrites the balance. Existing triggers continue to enforce archived-product rules, expiry-tracking consistency, and immutable movements.

## Local verification

Run from the project root:

\`\`\`powershell
python -m unittest discover -s tests -v
\`\`\`

For a first-time local database only, run:

\`\`\`powershell
python init_db.py
python app.py
\`\`\`

Do not run \`python init_db.py\` again if the database already exists; initialization intentionally refuses to overwrite it.

## Scope boundary

Sales, FEFO sale allocation, disposal, manual stock adjustments, authentication, supplier integration, and external AI/API services are not part of Phase 6.
