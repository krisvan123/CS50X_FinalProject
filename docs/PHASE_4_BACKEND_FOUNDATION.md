# WarungWise — Phase 4: Backend Foundation

**Phase:** 4 — Backend Foundation  
**Status:** Foundation files committed; local runtime verification remains pending  
**Related documents:** [Project Brief](PROJECT_BRIEF.md) · [Requirements and User Flows](REQUIREMENTS_AND_USER_FLOWS.md) · [Database Design](DATABASE_DESIGN.md)

## 1. Phase Objective

Establish a small, understandable Flask application that can connect to the existing SQLite schema, render a real database-backed dashboard, explain first-time database setup, and handle common request failures without exposing stack traces or database internals.

This phase deliberately does not implement product forms, sales, receipts, stock adjustments, restock recommendations, or reports. Those workflows belong to later milestones and must not be implied to be available merely because dashboard placeholders are visible.

## 2. Files Added

| File | Responsibility |
|---|---|
| app.py | Flask application factory, dashboard route, health endpoint, IDR display filter, and user-facing error routes |
| database.py | Request-scoped SQLite connection, row mapping, foreign-key enforcement, busy timeout, and teardown cleanup |
| requirements.txt | Flask runtime dependency |
| templates/base.html | Shared page layout, navigation shell, page metadata, and responsive structure |
| templates/setup.html | First-time database initialization instructions |
| templates/index.html | Dashboard metrics and recent stock movement area |
| templates/error.html | Generic not-found and server-error page |
| static/css/styles.css | WarungWise visual system and responsive styles |
| tests/test_app.py | Standard-library unittest smoke tests for setup handling, dashboard, readiness, and 404 behavior |

The existing schema, initializer, and .gitignore remain the source of truth for database structure, safe initialization, and excluding local data files. No production database file or sample transaction data is committed.

## 3. Application Behavior

### Dashboard

The GET / route reads active-product count, low-stock product count, batches nearing expiry, expired batches with quantity remaining, today's recorded sales revenue, and recent stock movements. Values are calculated from database records. An empty database shows zero-valued metrics and an informative empty state; it does not invent sample totals.

The dashboard uses the current local machine date as the business date for expiry checks and today's sales. Operation timestamps remain recorded in UTC in the database. The same date convention must be preserved in later inventory and reporting routes.

### Database setup

The app does not silently initialize a database on a user's behalf. If the configured local database file does not exist, the dashboard explains how to run python init_db.py. The initializer refuses to overwrite an existing database.

### Database connections

Each Flask request uses a connection cached on Flask's g object. Every connection enables SQLite foreign-key enforcement and has a finite busy timeout. Connections are closed at the end of the application context and unfinished transactions are rolled back.

### Health endpoint

GET /health returns a small JSON readiness result. It does not expose database paths, SQL errors, or internal configuration. A missing or unreadable database produces a non-success status so the issue is visible during local troubleshooting.

### Error handling

A not-found request receives a readable 404 page. Unexpected application errors receive a generic 500 page. Database errors on the dashboard are logged server-side and result in a generic message rather than leaking internal details to the browser.

## 4. Design and Dependency Notes

The interface uses a green/teal and neutral palette and includes responsive layouts, visible status text, keyboard focus styling, a skip link, and empty states. Bootstrap 5.3.8 is included through the official jsDelivr stylesheet URL with Subresource Integrity metadata; local CSS provides the WarungWise visual treatment. Core inventory calculations remain server-side.

The runtime dependency is Flask. SQLite, dates, logging, path handling, and CSV support in later phases can use the Python standard library. There is no paid API, AI API, payment integration, or cloud requirement.

The local development server binds to 127.0.0.1. Debug mode is disabled by default. The current application factory generates an ephemeral secret key if WARUNGWISE_SECRET_KEY is not supplied; deployments that need stable sessions must supply an environment variable and undergo a separate security review. The current local version does not implement authentication.

## 5. Setup and Run Instructions

Run these commands from the repository root in a terminal.

### Create and activate a virtual environment

Windows PowerShell:

    py -m venv .venv
    .\.venv\Scripts\Activate.ps1

macOS or Linux:

    python3 -m venv .venv
    source .venv/bin/activate

### Install the dependency

    python -m pip install -r requirements.txt

### Initialize a new local database

    python init_db.py

The command creates instance/warungwise.db only when no database exists at that path. It applies schema.sql and performs SQLite integrity and foreign-key checks. It inserts the default expiry-warning setting but does not create product or transaction demo data.

### Start the application

    python app.py

Open http://127.0.0.1:5000 in the browser. To inspect readiness, open http://127.0.0.1:5000/health. A ready database returns JSON with status set to ok.

## 6. Test Instructions

Run the smoke tests from the repository root:

    python -m unittest discover -s tests -v

The tests use temporary SQLite databases and do not operate on the user's local application database. They cover the first-time setup page, readiness when no database exists, loading an empty dashboard after initialization, database-backed product counts, foreign-key readiness, and not-found behavior.

**Verification status:** The shared automated test suite passed in GitHub Actions on Python 3.12, including all six Phase 4 smoke tests ([run details](https://github.com/krisvan123/CS50X_FinalProject/actions/runs/39202850512)). Running the same command locally is still recommended to confirm the developer's workstation setup. No end-to-end stock-receipt or sales workflow test is claimed by this phase.

## 7. Phase 4 Acceptance Checklist

- Flask application factory exists and accepts test configuration.
- Dashboard metrics are read from SQLite using parameterized date values.
- Missing database state is handled with an actionable setup page.
- SQLite foreign keys are enabled per connection and request connections are closed.
- Health and generic error routes do not expose internal details.
- UI structure and styles adapt to smaller screens.
- Runtime dependency and local run/test instructions are documented.
- Tests are present and their status is reported honestly.
- Product, sales, receipt, and disposal workflows remain explicitly out of scope for this phase.

## 8. Follow-on Milestone

Product Management is specified and implemented in [Phase 5 — Product Management](PHASE_5_PRODUCT_MANAGEMENT.md). The shared Phase 4 smoke tests have passed in CI; local workstation verification remains a separate check.
