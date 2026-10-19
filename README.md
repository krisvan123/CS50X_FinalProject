# WarungWise
**Smarter Stock. Less Waste. Better Decisions.**

#### Video Demo: PENDING — replace this line with the public or unlisted video URL before CS50x submission.

## Description

WarungWise is a local-first inventory and expiry-management web application designed for small Indonesian neighborhood shops (warungs). It focuses on a practical operational problem: a shop needs to know not only how many units it has, but also which delivery batch those units came from, when that batch expires, how stock changed, and what its recent sales suggest about replenishment.

The project uses Python, Flask, SQLite, Jinja templates, HTML, CSS, JavaScript, and Bootstrap. Its purpose is not to claim that a forecasting model can predict demand perfectly. Instead, WarungWise demonstrates transparent business rules that can be inspected, tested, and explained. It does not require a paid AI service, a paid business API, a supplier integration, or a separate database server.

## Features

### Product catalogue
Create, edit, search, filter, and archive products. Product records include a name, optional SKU/category, unit, reference cost, selling price, minimum-stock threshold, lead time, safety stock, and an expiry-tracking preference. SKUs are unique without regard to case. Archiving preserves history and is blocked when a batch still has remaining stock.

### Batch receipts and expiry management
Each delivery is entered as a distinct stock batch with its own received date, unit cost, quantity, and expiry date where expiry tracking is enabled. A batch’s original receipt details are protected from silent edits. Expiry status is derived from saved batch data, and expired quantities do not count as sellable stock.

### Sales and FEFO
The current interface records one product line per sale transaction to keep the initial workflow focused; the requested quantity may still be allocated from multiple batches. When expiry tracking is enabled, allocation uses First Expired, First Out (FEFO): the earliest eligible expiry is consumed first. Sales retain a selling-price snapshot so changing the current product price does not rewrite historical revenue.

Backdated sales are checked against the movement history of each candidate batch. A sale is not accepted when its quantity would make the batch balance negative on the entered business date or after a later recorded movement. This is stricter than checking the current quantity alone.

### Waste and stock-count corrections
The **Waste & corrections** workflow records disposal of damaged, expired, or otherwise unsellable stock, as well as inbound/outbound physical-count corrections against an existing batch. Every action requires a reason and creates an immutable movement record. Disposal value is computed from the disposed quantity and the batch’s stored unit cost; an expiry alert by itself is not treated as a realized loss.

### Dashboard, recommendations, and reports
The dashboard summarizes saved records, low-stock products, near-expiry batches, expired batches, sales, and recent movements. Rule-based restock recommendations use recent observed sales, lead time, safety stock, and current sellable inventory. They are estimates, not purchase orders or guaranteed forecasts.

The Reports page supports date-filtered sales and movement analysis, a daily gross-revenue trend, top products, a current stock snapshot, and CSV exports. It reports gross revenue separately from recorded disposal cost and does not claim either metric is net profit. Inventory snapshots show current balances; the app does not reconstruct historical stock snapshots. Workspace settings make the expiry-warning window configurable from 0 to 365 days.

## Technology and project structure

- `app.py` defines the Flask application factory, routes, server-side validation, sale allocation, reports, exports, settings, and stock-action workflows.
- `database.py` opens a request-scoped SQLite connection, enables foreign-key enforcement, and closes connections during Flask teardown.
- `schema.sql` defines products, operations, batches, sales, sale items, stock movements, application settings, constraints, triggers, and audit views.
- `init_db.py` safely initializes a new local database, runs SQLite integrity/foreign-key checks, and refuses to overwrite an existing database.
- `requirements.txt` lists the Python package dependency.
- `templates/` contains the shared layout and pages for dashboard, products, batches, sales, stock actions, movement ledger, recommendations, reports, settings, setup, and errors.
- `static/css/styles.css` styles the responsive interface and shared components. `static/js/app.js` adds accessible presentation effects and the live sale summary.
- `tests/test_app.py` contains the unittest suite. Tests use temporary databases and do not touch the operator’s local database.
- `DESIGN.md` explains the technical architecture, database invariants, transaction flows, and design trade-offs.
- `docs/` records the project brief, user flows, schema choices, implementation milestones, and review notes.
- `.github/workflows/tests.yml` runs the automated test suite on pushes and pull requests to `main`.

## Local setup

Use Windows PowerShell from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python init_db.py
python app.py
```

Use an installed Python version supported by Flask 3.x; if Python 3.12 is unavailable, replace `py -3.12` with the launcher version installed on your machine. Open the local URL printed by Flask, typically `http://127.0.0.1:5000`.

The initializer does not add synthetic data. Create a product through the interface, receive a batch, record a sale, then inspect the movement ledger, recommendations, and reports. To demonstrate expiry behavior, configure a product to track expiry and receive a batch with a valid expiry date.

**Data safety:** `python init_db.py` refuses to overwrite an existing database. It creates `instance/warungwise.db` only for a new installation. Back up that file before database maintenance. The database, journals, and local instance folder are excluded from Git.

## Running tests

```powershell
python -m unittest discover -s tests -v
```

The integrated automated suite currently has 62 passing tests on Python 3.12 in [GitHub Actions run 39215925741](https://github.com/krisvan123/CS50X_FinalProject/actions/runs/39215925741). Tests cover core form validation, FEFO allocation, expiry restrictions, reports/CSV, disposal and count corrections, warning settings, replay protection, historical-balance consistency, HTTP security headers, and concurrent stock requests. Automated tests do not replace visual browser review or deployment-specific security testing.

## Main routes

| Route | Purpose |
|---|---|
| `/` | Dashboard |
| `/products` | Product catalogue |
| `/batches` and `/batches/new` | Batch register and stock receipt |
| `/sales` and `/sales/new` | Sales history and new sale |
| `/stock-actions/new` | Disposal and stock-count corrections |
| `/movements` | Chronological movement ledger |
| `/recommendations` | Explainable restock advice |
| `/reports` | Date-filtered reports |
| `/reports/export/<type>` | Sales, movement, or inventory CSV |
| `/settings` | Expiry-warning setting |
| `/health` | Local readiness check |

## Scope and limitations

WarungWise is designed for one local shop and one operator. It does not include user accounts, roles, multi-shop access, cloud sync, supplier purchasing orders, payment processing, refunds, or machine-learning-based forecasting. Restock suggestions cannot account for unrecorded sales, promotions, seasonality, supplier minimums, or cash constraints.

The local development server is not intended for direct public-internet exposure. A public deployment would require a separate security review, authentication and authorization decisions, production server setup, stable secret configuration, HTTPS, backups, and operational monitoring.

## AI assistance and academic integrity

ChatGPT assisted with planning, drafting, code refinement, testing, documentation, and interface styling in this project. AI-use disclosures have been added to relevant code areas, but the project author must review and understand the submitted implementation and ensure that comments accurately describe the assistance provided. The official [CS50x 2026 Final Project instructions](https://cs50.harvard.edu/x/project/) permit external AI tools for the final project while requiring their use to be cited in code comments.

## Before submission

Record a video of no more than three minutes and replace the pending Video Demo line at the top with its URL. The opening of the video must display the project title, the student's name, GitHub and edX usernames, city and country, and the recording date. Then demonstrate the main workflow, including product creation, batch receipt, sale, stock correction/disposal, reports, and CSV export. Complete the Phase 12 manual test/security gate before treating the project as ready to submit.
