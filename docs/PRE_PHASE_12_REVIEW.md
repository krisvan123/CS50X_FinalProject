# Pre-Phase 12 Quality Review

**Review date:** October 19, 2026  
**Reviewed commit:** `507b512555d8634378d4fd080150ceaf886d5e9b`  
**Automated verification:** [GitHub Actions run 39213007801](https://github.com/krisvan123/CS50X_FinalProject/actions/runs/39213007801) — 57 tests passed on Python 3.12.  
**Status:** Core pre-Phase 12 improvements are implemented. This document does not claim that the full security or browser review is complete.

## Improvements completed before Phase 12

- Added a batch-level workflow for disposal and inbound/outbound stock-count corrections. Each action requires a reason, is stored in the immutable ledger, and updates stock through the database movement trigger.
- Added a configurable expiry-warning window on `/settings`, persisted in `app_settings`.
- Added a selected-period recorded-disposal-value metric in Reports, based on disposal movements multiplied by the affected batch's stored unit cost.
- Added per-form request tokens for receipts, sales, and stock actions. Resubmitting the same rendered form token does not create a second stock-changing operation.
- Added a historical-batch-capacity check for backdated sales. The quantity is limited by the available balance on that date and the minimum remaining balance after later movements.
- Restricted disposal and count-correction actions to today's local business date, avoiding retroactive stock-count/disposal edits through the regular workflow.
- Made the one-product-line-per-sale scope explicit in requirements, documentation, and the README. A sale line may still consume multiple batches using FEFO.
- Added a root README describing setup, core files, routes, the data model, test command, limitations, and the required demo-video item.
- Added AI-assistance disclosures to relevant code areas and documented the obligation to review and understand the implementation before submission.

## Current strengths

- A small Flask/SQLite stack with no paid AI or external business API dependency.
- Database constraints, triggers, foreign-key enforcement, and audit views protect inventory consistency.
- Server-side validation and CSRF checks cover state-changing workflows.
- Sales, receipts, and stock actions use transactions with rollback on database failure.
- Reports distinguish gross revenue from profit and recorded disposal cost from estimated loss.
- The latest CI run completed all 57 automated tests successfully.

## Explicit remaining work for Phase 12

1. Perform browser-based manual checks of every page at desktop and narrow/mobile widths, including keyboard navigation, reduced-motion mode, and unavailable external font/CDN behavior.
2. Test actual concurrent duplicate POSTs as well as sequential resubmissions; the database unique constraint must remain the final protection under races.
3. Review validation boundaries, exception paths, CSRF coverage, cookie/session behavior, CSV formula protection, error messages, and database rollback behavior.
4. Verify that both audit views show zero differences after receipts, sales, disposals, and inbound/outbound corrections.
5. Review historical-date edge cases beyond the existing test, including multiple same-day movements and backdated receipts.
6. Confirm the local setup workflow on the author's computer and protect any existing `instance/warungwise.db` before testing.
7. Keep the application local-only until a separate deployment threat model, authentication/access-control plan, stable secret configuration, HTTPS, and backup plan exist.

## Submission items not yet complete

- The Video Demo URL is deliberately marked pending in `README.md`; no video URL has been invented.
- The browser-level review and full Phase 12 security review have not been performed in this commit.
- The final README should be checked after recording the video and before running the official CS50x submission command.

## Assessment boundary

The 57-test CI result is evidence that the currently automated scenarios pass. It is not a 10/10 guarantee, an official CS50 grade, a penetration-test result, or evidence of real-world shop validation. Those claims require separate evidence.
