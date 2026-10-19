# Phase 13 — Documentation and Demo Preparation

**Status:** Demo assets prepared in advance; Phase 13 is not complete. It remains gated by the Phase 12 manual browser/security review and recording the actual demo video.

## 1. Isolated demo database

The optional `seed_demo.py` script creates fictional records in `instance/warungwise-demo.db`. It does not write to the normal `instance/warungwise.db` database. The app can be pointed at the demo database through the `WARUNGWISE_DATABASE` environment variable.

From Windows PowerShell at the project root, after installing the requirements:

```powershell
python seed_demo.py
$env:WARUNGWISE_DATABASE = (Resolve-Path .\instance\warungwise-demo.db).Path
python app.py
```

Open the local URL printed by Flask. To run the ordinary local database again in that PowerShell session, use:

```powershell
Remove-Item Env:WARUNGWISE_DATABASE -ErrorAction SilentlyContinue
python app.py
```

The script refuses to combine the synthetic dataset with unrelated existing records and is a no-op if the complete demo dataset is already present. It never deletes existing records. The demo dataset is fictitious and must not be presented as real shop data.

## 2. Dataset contents

The seed includes 12 products, 13 stock batches, 29 sales, one disposal operation, and one positive count correction. Receipt, sale, and stock-action records are connected to their stock movements so that dashboard and report values are derived from the actual database ledger.

The dataset contains these demo scenarios:

- A sugar product below its minimum-stock threshold.
- An expired biscuit batch that is still on hand and should be excluded from sellable stock.
- Multiple near-expiry batches, including noodles, milk, eggs, and chips.
- Two noodle batches with different expiry dates to support a FEFO walkthrough.
- Sales across the past few weeks, including several transactions dated today.
- A damaged-packaging disposal and a positive physical-count correction.
- Valid synthetic costs and prices in whole Indonesian rupiah.

Dates move relative to the date when the seed script is run. The examples should therefore remain relevant when the project video is recorded later.

## 3. Suggested demo walkthrough

A concise walk-through can use this order:

1. Start on the Dashboard and explain the active-product, low-stock, expiry, and sales-today indicators.
2. Open Products and Stock batches to show that expiry is stored per batch, not only per product.
3. Open Restock advice and explain the rule-based recommendation using recent recorded sales, lead time, safety stock, and sellable stock.
4. Record a small sale of Chicken Instant Noodles and point out that the earlier-expiry eligible batch is consumed first.
5. Open Waste & corrections and record a clearly labelled demo-only action against a remaining demo batch.
6. Inspect Movements and Reports, explain that sales, disposal, and correction activity appears in the ledger, then export a CSV.

Only perform additional writes against the separate demo database during rehearsal. Do not use invented values to imply real customer transactions, real business performance, or validated forecasts.

## 4. Optional Vercel Hobby portfolio preview

The repository is configured for deployment on Vercel's free Hobby plan for personal, non-commercial projects. From the Vercel dashboard, choose **Add New → Project**, import `krisvan123/CS50X_FinalProject`, keep the project root at the repository root, select Hobby, and deploy. The app entry point is `wsgi:app`; static assets are served from `public/static/`.

On Vercel, `wsgi.py` uses the writable temporary path `/tmp/warungwise-demo.db`, seeds only fictional data, and enables `DEMO_READ_ONLY`. A request guard rejects all methods other than GET, HEAD, and OPTIONS. The public demo is intended for viewing the inventory and reporting pages; use the local demo for recording sales and other changes.

**Important limitations:** Vercel Functions do not offer durable local SQLite storage. Temporary database content may be recreated on cold starts or different instances. Choose the free Hobby plan, avoid paid add-ons, and do not enter real inventory, personal information, or secrets into the public preview. The hosted demo has no user authentication and is not a production inventory service.

## 5. Phase 13 exit checklist

- [ ] Complete and record the Phase 12 manual browser/security review.
- [ ] Verify all demo routes at desktop and narrow/mobile widths.
- [ ] Rehearse the primary workflow against the demo database, including FEFO and CSV exports.
- [ ] Confirm the README setup and demo commands work on the submission machine.
- [ ] Record a video of no more than three minutes and replace the pending demo URL in the README.
- [ ] Verify the final Git working tree has no local database, secrets, or other private files.
