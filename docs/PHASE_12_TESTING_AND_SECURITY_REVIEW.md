# Phase 12 — Testing and Security Review

**Status:** In progress — automated CI gate passes; manual browser and final security review are still required.  
**Current reviewed code commit:** `78b8a160d05ca971c4e56a10c5670bf83d34b739`  
**Automated verification:** [GitHub Actions run 39216329904](https://github.com/krisvan123/CS50X_FinalProject/actions/runs/39216329904) — **63 tests passed** on Python 3.12 on October 19, 2026.

## 1. Phase 12 goal

Confirm that the core inventory workflows preserve their data invariants under invalid input, duplicate submission, competing requests, and ordinary database failures. Confirm that the rendered application applies a conservative set of browser security headers and that the documentation accurately describes what was tested. Automated CI evidence is only one part of this phase; the app still needs a manual review in the author's local browser.

## 2. Implemented safeguards reviewed

- **CSRF:** State-changing routes validate a session-bound CSRF token before acting.
- **Duplicate requests:** Receipts, sales, and stock actions have high-entropy form request tokens stored under a unique database constraint.
- **Serialized inventory writers:** Those three stock mutation routes acquire a SQLite `BEGIN IMMEDIATE` write reservation before checking duplicate tokens and reading the stock balance. A competing request waits for the current write and then validates against the latest committed balance, subject to SQLite's configured five-second busy timeout.
- **Transactional changes:** Receipt, sale, disposal, and count-correction changes commit their operation and movement records together. An error path rolls back unfinished writes.
- **Historical sales:** The sale workflow checks each batch's movement history so that a backdated sale does not create a negative interim balance after later movements.
- **Inventory auditability:** The schema exposes `v_batch_balance_audit` and `v_sale_item_allocation_audit` to compare persisted balances/allocation against movement records.
- **CSV exports:** Spreadsheet formula-leading text is sanitized and exports use an attachment response and UTF-8 BOM.
- **HTTP headers:** The app adds CSP, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, and a restrictive `Permissions-Policy`.
- **Browser caching:** Dynamic pages use `Cache-Control: no-store`; static assets remain eligible for their normal caching policy.
- **Session defaults:** Session cookies are HttpOnly and SameSite=Lax. A local-process random secret is used unless `WARUNGWISE_SECRET_KEY` is provided; a public deployment needs separate stable secret management.

## 3. Automated tests added during this review

| Scenario | Expected invariant | Latest result |
|---|---|---|
| Two concurrent receipt POSTs reuse the same request token | One receipt, one batch and one positive movement; balance changes once | Pass |
| Two concurrent sales use different tokens and each requests four units from five available | One succeeds, the other is rejected; one unit remains | Pass |
| Two concurrent disposals use different tokens and each requests four units from five available | One succeeds, the other is rejected; one unit remains | Pass |
| Same stock-action request token is posted twice sequentially | Only one operation and one movement are recorded | Pass |
| Backdated sale would make a later batch balance negative | Sale is rejected and existing balance/audit remains unchanged | Pass |
| Browser security header policy | Required headers exist; dynamic HTML is no-store and static CSS is cacheable | Pass |
| Missing CSRF token on disposal/settings POST | Both requests are rejected with HTTP 400; stock and settings remain unchanged | Pass |
| Disposal/correction workflows | Reasons are required; overdraws are rejected; batch audit remains balanced | Pass |
| Expiry-warning settings | Valid value persists and out-of-range values are rejected | Pass |

The latest CI run completed all **63** tests on Python 3.12. The full output is linked above. This is evidence for those tested scenarios, not proof that every possible interleaving or environment has been tested.

## 4. Manual browser checklist — still outstanding

Complete this checklist in the local application after backing up the existing database. Do not delete or reinitialize a populated database to perform these checks.

- [ ] Start the app using the documented Windows PowerShell commands and confirm `/health` and `/` behave as expected.
- [ ] Visit every primary page: Dashboard, Products, Stock batches, Sales, Waste & corrections, Movements, Restock advice, Reports, and Settings.
- [ ] At desktop and narrow/mobile viewport widths, inspect clipping, overflowing tables/forms, layout spacing, navigation, and whether the primary actions remain usable.
- [ ] Navigate with keyboard only. Confirm the skip link, visible focus state, meaningful labels, error messages, and page order are usable.
- [ ] Enable the operating system/browser reduced-motion preference. Verify decorative movement and reveal/count effects do not interfere with reading or focus.
- [ ] Inspect the browser Network/Console panels for blocked CSP resources or JavaScript errors. Check that the app remains readable if Google Fonts or Bootstrap's external CSS CDN is unavailable.
- [ ] Inspect response headers in developer tools; verify CSP does not block required resources and that dynamic business pages carry `Cache-Control: no-store`.
- [ ] Run a full demo flow: create product, receive batch, sell stock, record disposal/count correction, inspect movement history and audit views, run reports, download all CSV exports, and change the expiry warning window.
- [ ] Check that the Git working tree contains no local database, secrets, private business data, temporary logs, or generated files before committing.

## 5. Additional security/robustness checks to consider

- Test database busy timeout/error handling deliberately; the code currently returns a controlled 503 response if it cannot acquire the write reservation.
- The automated threaded tests exercise concurrent Flask test-client requests; a separately hosted WSGI-server load/concurrency run has not yet been performed.
- Exercise more same-day movement-order and backdated-receipt combinations; the existing temporal test covers one important boundary, not every historical schedule.
- Verify archive-vs-receipt and product-edit-vs-sale races under concurrent requests.
- Review every database trigger/constraint and ensure a failed operation never leaves orphan rows or mismatched audit views.
- Confirm any secret used for a hosted/demo environment is stable and secret; do not expose the local development server directly to the public internet.
- Review browser CSP behavior on the actual local page rather than assuming response-header tests prove frontend compatibility.

## 6. Exit criteria

Phase 12 is not complete until:
1. The 62-test CI suite continues to pass for the final code commit.
2. The manual browser checklist above is actually completed and recorded.
3. No known inventory balance/audit mismatch remains in mixed-workflow tests.
4. Error paths and the local setup procedure are understood and checked by the project author.
5. The project author can explain the database invariants, FEFO logic, historical sales check, CSRF/request tokens, and report calculations.

The 62-test result does not guarantee a 9.8/10 or 10/10 score, is not an official CS50 grade, and is not a penetration-test certificate. It is a verified checkpoint for the tested behavior only.
