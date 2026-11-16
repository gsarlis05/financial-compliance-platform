# 09 — Milestone 1 Acceptance Criteria: "Secure tenancy + core ledger"

Status: **APPROVED v2 (2026-11-03)**. Includes Milestone 0 foundations. Phase 1 = M1 (this document) + M2 (criteria in [12 §3](12-fpa-testing-and-acceptance.md)). Milestone 1 is accepted only when **all** criteria pass in CI and in a reviewed demo on staging (synthetic data).

## Business purpose
Give a firm a secure, multi-tenant workspace where staff can maintain a chart of accounts, record
balanced journal entries through an approval workflow, correct them only via reversals, lock
periods, and produce a trial balance they can trust. That trustworthy base is required before any
tax or AI features.

## Out of scope for M1
Documents, bank import, FX/multi-currency posting (single-currency EUR entities only), VAT, tax, AI, financial statements.

## A. Authentication
- AC-A1 Users log in only via OIDC. A login without an MFA `amr` claim is rejected with an actionable message.
- AC-A2 Session cookie is `__Host-`, `HttpOnly`, `Secure`, `SameSite=Lax`. Idle (30 min) and absolute (12 h) timeouts are enforced (tested with a clock fake).
- AC-A3 State-changing requests without a valid CSRF token → 403.
- AC-A4 Step-up: unlocking a period or changing roles requires an authentication ≤ 5 min old, otherwise the API returns `step_up_required`.
- AC-A5 Logout invalidates the server session and the IdP session.

## B. Authorization & tenant isolation
- AC-B1 Every API route declares a permission. CI fails if one doesn't (tested by adding an undeclared route in a test).
- AC-B2 Role × permission matrix tests pass for all system roles (allow and deny cases).
- AC-B3 **Cross-tenant suite:** for every route, tenant A's user receives 404 for tenant B's resources, and no B data appears in responses (including list endpoints and exports).
- AC-B4 DB tests: without `app.tenant_id`, every tenant table returns 0 rows to `app_rw`. Inserting a foreign `tenant_id` fails. `app_rw` has `NOBYPASSRLS`.
- AC-B5 CI schema check fails when a tenant table lacks FORCE RLS/policy or tenant classification.
- AC-B6 Entity-scoped users cannot see entities outside their assignment (API + DB tests).
- AC-B7 Tenant admin cannot grant a permission they do not hold, and the default admin cannot approve entries.
- AC-B8 Workspaces have a kind (FIRM, BUSINESS, PERSONAL). Feature entitlements are enforced server-side (e.g. the PERSONAL kind cannot create a second legal entity or access firm-only routes), as tested via the API, not just the UI.
- AC-B9 A user belonging to two workspaces sees data only from the workspace in the URL path. The workspace switcher shows a distinct label/colour per kind, and a workspace id in a request body is ignored.

## C. Ledger
- AC-C1 Posting is rejected for: unbalanced entries (incl. 0.01 difference), < 2 lines, zero/negative amounts, both sides on one line, non-postable/inactive/other-entity accounts, a date outside any period. Each returns a distinct problem+json `code` and a field-level message shown in the UI.
- AC-C2 The DB rejects an unbalanced post and any UPDATE/DELETE of posted entries/lines even when the application is bypassed (direct SQL tests as `app_rw`).
- AC-C3 Approval policy `threshold` and `always` enforce SoD: the preparer cannot approve. Changing an approved entry invalidates the approval (`content_hash`).
- AC-C4 Gapless, unique `entry_no` per journal & FY under 50 concurrent posts.
- AC-C5 Idempotency: repeating a post with the same key returns the original result without a duplicate.
- AC-C6 Reversal creates a mirrored entry linked both ways. A second reversal is rejected. A reversed pair nets every affected account to zero (property test).
- AC-C7 Period states: posting into LOCKED is rejected. SOFT_CLOSED requires the privilege and is audited. Unlock requires 2 distinct approvers with step-up, is time-boxed, re-locks automatically, and postings during the window are tagged.
- AC-C8 Trial balance for any date/period balances. The property test (≥ 1,000 random balanced entry sets) always yields Σdebit = Σcredit and snapshot = Σlines.
- AC-C9 Rounding: all money handling uses `Decimal`. Passing a float to `Money` raises. The lint rule blocks `float(` in domain code. Documented HALF_UP tests at .005 boundaries pass. Amounts up to 10^13 are handled without loss.
- AC-C10 The nightly integrity job detects a deliberately corrupted balance snapshot and a broken audit hash in test, raising a visible alert.
- AC-C11 Trial balance and GL CSV exports neutralise formula injection.
- AC-C12 Every posted entry receives a strictly increasing per-tenant `posting_seq` (the watermark used by FP&A). Concurrent posts produce no duplicates, and the TB as of watermark W is reproducible after later postings.

## D. Audit trail
- AC-D1 Every create/update/state change on tenancy, roles, accounts, periods and entries writes an audit event in the same transaction (a forced rollback test leaves no orphan events and no unaudited change).
- AC-D2 The hash chain verifies for the fixture data, and tampering with any event is detected.
- AC-D3 Audit events contain no secrets or document content. Sensitive fields are digested.

## E. Logging & errors
- AC-E1 The log redaction test proves that names, emails, TINs, IBANs and amounts injected into requests do not appear in application logs.
- AC-E2 Unhandled exceptions return a problem+json with `correlation_id` and no stack trace, and are reported to the error tracker with scrubbing.
- AC-E3 No `except: pass` / silent catch in domain code (Semgrep rule).

## F. UX validation
- AC-F1 The journal entry form shows live debit/credit totals and the difference (computed with a decimal library), blocks submit when unbalanced, and displays server errors next to fields.
- AC-F2 Posted entries render read-only with the "Reverse" action only (if permitted). The UI offers no edit.
- AC-F3 The UI shows period status clearly. Posting into a non-open period explains why and who can help.
- AC-F4 WCAG 2.2 AA automated checks (axe) pass on M1 screens. EN and EL strings are present for M1 screens.

## G. Quality gates
- AC-G1 Domain-module line coverage ≥ 90% and branch coverage ≥ 85%. Ledger posting code is 100% branch-covered.
- AC-G2 CI green: lint, mypy strict (domain), Semgrep, SCA (no high/critical unaccepted), secret scan, import-linter contracts.
- AC-G3 OpenAPI spec is generated and published. Docs (user guide, runbooks, ADRs) are updated. The "Known limitations" section is completed.
- AC-G4 Migrations are reviewed in the PR. **No production environment or migration exists or is applied in M1.**
- AC-G5 The sample dataset loads on staging, and the demo script runs end-to-end: invite user → create CoA → draft → approve → post → reverse → lock period → TB.

## Deliverables checklist (per directive)
Business requirements ✔ (this doc + PRD) · Technical design ✔ (SAD, docs 03–05) · DB changes (migrations + ERD update) · Security controls (doc 04, 07) · Automated tests · Edge-case tests (C1, C7, C9) · Sample data (M1-13) · User-facing validation (F) · Documentation (G3) · Known limitations.
