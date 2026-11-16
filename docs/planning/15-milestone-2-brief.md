# 15 — Milestone 2 Implementation Brief: Registers, banking, basic reporting

Status: **IN PROGRESS** (product owner go-ahead 2026-11-03: "Continue developing the application
according to our existing roadmap, ensuring that everything remains compatible with future cloud
deployment"). Backlog: [08 §M2](08-implementation-backlog.md).

## 1. Business purpose
Turn the M1 ledger into books a business can run day to day. That means analysing postings by
department or project, tracking who owes what and when (open items and ageing), coding VAT
correctly on every line, keeping supporting documents, importing and reconciling the bank, and
producing a P&L, balance sheet and cash flow statement. These are also the inputs Phase 2 needs
(cash forecast, budgets, KPIs) through the `reporting.actuals` read model.

## 2. Dependencies and regulatory requirements
- Builds on M1: immutable ledger, row-level security, audit, the permission catalogue and the
  integrity checks, plus M2-0 packaging.
- Cyprus VAT: standard rate 19%, reduced rates 9%, 5% and 3%, zero rate, exempt, and EU reverse
  charge. **The VAT code catalogue is data, versioned by effective date, and every rate is marked
  "unverified" until a Cyprus tax professional confirms it** (owner decision #2 is still open). No
  VAT return is produced in M2.
- Bookkeeping retention (Cyprus: at least 6 years). Documents are retained and never deleted by users.
- GDPR: counterparties and documents contain personal data. Their fields are classified, never
  logged, and isolated by row-level security.

## 3. Defaults taken for the open questions (change them any time)
| Question | Default in M2 |
|---|---|
| Other currencies than EUR? (unanswered) | **EUR only in Phase 1.** M2-10 (FX) moves to M6, as the backlog allows. Lines keep a currency column, so adding FX later needs no rework. |
| Bank and statement format? (unanswered) | **Both:** ISO 20022 CAMT.053 (XML), which most EU banks export, and CSV with a saved, per-bank column mapping. This covers any Cyprus bank without knowing which one. |
| Antivirus scanning for uploads | ClamAV as a separate container (locally and on ECS). It is swappable for GuardDuty Malware Protection for S3 later. |

## 4. Technical approach and order
| # | Item | Approach |
|---|---|---|
| M2-1 | Dimensions | `dimension` and `dimension_value` tables per entity (department, project, cost centre, custom), with optional dimension tags on journal lines, rules per account (required, allowed, blocked), dimension filters on TB/GL, and a UI to manage dimensions. |
| M2-2 | Counterparties + open items | Counterparty register (PII fields classified). An open item is created from a posted entry on a control account; settlements are matched by posted entries; there is an ageing report. Sub-ledger postings use `ledger.api` with `source`/`source_ref` (doc 05 §8). |
| M2-3 | VAT codes | Versioned VAT code catalogue as data (seeded for CY, marked unverified; the 3% rate is withheld until verified). A `tax_code` on lines is validated against the accounting date, and VAT control accounts accept only VAT-coded postings. |
| M2-6 | Taxonomy + mapping | Versioned report-line taxonomy (IFRS-style, small-company level), account → line mapping, and a completeness task that blocks statements while accounts are unmapped. |
| M2-7 | `reporting.actuals` | `fact_actuals_monthly` and `fact_cash_daily` read model, rebuilt from the ledger, verified nightly against the trial balance, and tagged with `posting_seq` watermarks. |
| M2-8 | Statements | P&L, balance sheet and indirect cash flow statement from the taxonomy, with comparatives and drill-down to entries, plus CSV/XLSX/PDF export. |
| M2-9 | Year-end | System CLOSING and OPENING entries through the normal approval workflow. Check: opening TB(FY+1) = closing balance sheet. |
| M2-5 | Bank | Bank accounts linked to ledger accounts. Hardened CAMT.053/CSV import (XXE-safe parser, size limits, duplicate detection by hash), matching rules, reconciliation, and the last-reconciled date. |
| M2-4 | Documents | S3 upload pipeline: MIME sniffing, AV scan, per-tenant KMS context, links to entries and open items, and retention. |

Every item follows the M1 patterns: tenant-owned models with RLS and composite foreign keys, a
permission on every route, an audit event per change, problem+json errors, money as `Decimal`, the
OpenAPI document regenerated, and the UI on top of the API. Cloud compatibility is enforced in CI by
the container smoke test (M2-0): S3 through the S3 API only, no local disk, configuration through
environment variables.

## 5. Acceptance criteria (headline; each PR lists its own)
- AC-M2-1: a posting to an account with a required dimension and no dimension value is rejected
  (application and database), and TB/GL filter by dimension.
- AC-M2-2: open items reconcile to their control accounts (Σ open = control balance), and ageing
  buckets are correct at any date.
- AC-M2-3: a VAT-coded line outside the code's validity window is rejected, and VAT control
  accounts reject uncoded lines.
- AC-M2-5: the same statement imported twice creates no duplicates; malicious XML (XXE, billion
  laughs) is rejected; a reconciled bank balance equals the statement closing balance.
- AC-M2-6/8: an unmapped account with a non-zero balance blocks statements; the balance sheet
  balances; P&L result = movement in equity; golden-file statements for Demo Trading match.
- AC-M2-7: the read model equals the trial balance for every month (nightly check) and can be
  rebuilt deterministically.
- AC-M2-9: after the close, the P&L accounts are zero, and opening TB(FY+1) = closing balance sheet(FY).
- AC-M2-4: an EICAR test file is rejected, a MIME/extension mismatch is rejected, and documents
  cannot be read across tenants (S3 key prefix plus RLS).

## 6. Risks
| Risk | Mitigation |
|---|---|
| Unverified VAT rates used as if authoritative | Every rate is flagged unverified in data and UI until signed off; no return or filing in M2. |
| Bank file parsing attacks | defusedxml, size and row limits, fuzz tests, imports run in a worker task, not the request. |
| Scope (L items) | One PR per item, in the order above; each PR stands alone and is reviewable. |

Licences: defusedxml (PSF), openpyxl (MIT), WeasyPrint (BSD) or similar for PDF, and ClamAV (GPL,
used as a separate service, not linked). All are acceptable.
