# Milestone 2 report: registers, banking, basic reporting

Status: **complete, awaiting product owner review** (PRs #20, #21, #96–#98 and #100–#105, stacked
after Milestone 1; each is reviewable on its own). No environment exists beyond local development
and CI, and no migration has been applied anywhere else (AC-G4). Brief:
[planning doc 15](planning/15-milestone-2-brief.md).

## What you can do now
On top of Milestone 1, you can:
- **Analyse:** tag entry lines with departments, projects or other dimensions, with required or
  blocked rules per account. Filter the trial balance and general ledger by them.
- **Customers and suppliers:** keep a register of customers and suppliers. Book invoices and
  payments against them, match payments automatically, and see ageing that always reconciles to
  the control accounts.
- **VAT:** code VAT on every line from a versioned Cyprus catalogue (rates marked *unverified*
  until your tax professional confirms them).
- **Statements:** map the chart of accounts to a financial taxonomy. Produce a **P&L, balance
  sheet and cash flow statement** with prior-year comparatives, drill-down to entries, and
  PDF/XLSX/CSV export in English or Greek.
- **Year end:** **close the year** through a reviewed closing entry, and re-open it if needed.
- **Bank:** import **bank statements** (CAMT.053 or CSV), match them to the ledger and **reconcile**.
- **Documents:** attach **documents** (virus-scanned, type-checked) to entries as evidence.
- **Navigation:** use the app through grouped menus, on desktop or phone.

Try it with `make demo` ([demo script](demo.md)). Its 17 steps run the whole year, from invoices to
the closed year. See the [user guide](user-guide/ledger.md).

## Items
| Item | PR | What |
|---|---|---|
| M2-0 Cloud packaging | #20 | container images, production settings (fail fast, TLS everywhere), readiness probe, production-like smoke test in CI ([cloud review](reviews/2026-11-03-cloud-readiness.md), ADR-0012) |
| M2-1 Dimensions | #21 | dimensions and values per entity, per-account rules, TB/GL filters |
| M2-2 Counterparties and open items | #96 | register, open items = control-account lines, allocations, ageing |
| M2-3 VAT codes | #97 | versioned catalogue (unverified), VAT control-account rules |
| M2-6 Taxonomy and mapping | #98 | IFRS-for-SMEs-style taxonomy v1.0, append-only mapping, completeness |
| M2-7 Actuals read model | #100 | monthly and daily facts with watermark, rebuild, drift check |
| M2-8 Statements | #101 | P&L, balance sheet, indirect cash flow, checks, exports (ADR-0013) |
| M2-9 Year-end close | #102 | closing entry through approval, closed-year guard, re-open (ADR-0014) |
| M2-11 Grouped navigation | #103 | five menus, keyboard accessible |
| M2-5 Bank | #104 | hardened CAMT.053/CSV import, worker, matching, reconciliation (ADR-0015) |
| M2-4 Documents | #105 | S3 vault, ClamAV, type sniffing, links, immutable evidence (ADR-0016) |
| M2-10 FX | — | moved to M6 as the brief allows (EUR only in Phase 1; decision #90) |

## Acceptance criteria (brief §5)
| AC | Evidence |
|---|---|
| M2-1 required dimension enforced (app and DB); TB/GL filter | `tests/ledger/test_dimensions.py` (including direct SQL) |
| M2-2 open items = control balance; ageing correct at any date | `tests/registers/test_open_items.py`; the demo reconciles 203,631.60 / 102,084.19 |
| M2-3 VAT code validity; VAT accounts need a code | `tests/ledger/test_vat.py` (including DB bypass) |
| M2-4 EICAR rejected; MIME mismatch rejected; no cross-tenant reads; no content in logs/audit | `tests/documents/test_documents.py` against **real ClamAV and S3 in CI**; the demo refuses EICAR |
| M2-5 no duplicates; XXE and billion laughs rejected; reconciled = statement closing; fuzzed parsers | `tests/banking/` (Hypothesis fuzzing in CI, plus 50,000 extra cases while building); the demo reconciles 371,514.38 |
| M2-6 unmapped balance blocks statements | `tests/metrics/test_mapping.py`, `test_statements.py` |
| M2-7 read model = ledger; deterministic rebuild | `tests/reporting/test_actuals.py` (property test); `actuals_verify` in `make ops-checks` |
| M2-8 BS balances; result = equity movement; golden file | `tests/metrics/test_statements.py` (property tests, also across a closed year); golden file `tests/devtools/golden/demo_statements_2026.json`, recomputed independently |
| M2-9 P&L zero after close; opening TB = closing BS | `tests/ledger/test_closing.py` (re-open and close reproduces the trial balance; DB guard); integrity check `closed_years_have_no_result` |
| M2-0 cloud packaging | `make container-smoke` in CI: TLS `verify-full`, read-only root filesystem, non-root, runtime role, scheduled jobs, import worker |

## Database changes (Milestone 2)
| Module | Migrations | Content |
|---|---|---|
| ledger | 0009–0015 | dimensions and rules; control accounts with line counterparty, reference and due date; VAT codes (global, read-only) and rules; closed-year posting guard, closing entries exempt from dimension rules, one live closing per year |
| registers | 0001–0004 | counterparties, allocations, open-item flags; allocation guard trigger |
| metrics | 0001–0002 | taxonomy (global, read-only), append-only account mapping |
| reporting | 0001–0003 | actuals facts and state; closing entries kept apart (`is_closing`) |
| banking | 0001–0003 | bank accounts, imports, lines, reconciliations; match guard, append-only reconciliations, `banking_pending_tenant_ids()` |
| documents | 0001–0002 | documents (immutable), links (same entity, posted lines) |

Every new table has FORCE row-level security and composite tenant keys. Every migration is
reversible (apply → zero → apply was tested for the new modules) and is listed in its PR.

## Security controls added
- **Hostile input:**
  - bank files are parsed by defusedxml with limits and fuzzing, by a worker rather than in the
    request;
  - documents are type-sniffed and virus-scanned, failing closed;
  - filenames are made safe;
  - every export is formula-safe.
- **Least privilege:**
  - the import worker runs as the runtime role and finds work through a function that returns IDs
    only;
  - reference data is read-only for the runtime role;
  - reconciliations and documents are append-only, enforced by both trigger and grant.
- **Evidence:**
  - documents are immutable and never deleted;
  - posted entries remain immutable, and a closed year refuses postings at the database level;
  - every change is audited (IBANs, counterparty names and emails are masked; document content is
    never logged).
- **Encryption when deployed:** documents use SSE-KMS with a tenant encryption context. Deployed
  settings fail fast without TLS, KMS, bucket or scanner settings.

## Quality
Measured on 2026-11-04 at the head of PR #105 (`make test`, fresh database):
- Backend: **792 tests pass**; overall **97.4% line / 90.5% branch** coverage. The money library is
  at 100% branch coverage (CI gate). Posting and correction code is covered by the ledger suites,
  including direct-SQL bypass tests.
- Frontend: **26 tests** (including axe on every new screen); ESLint strict, `tsc`, build.
- Every PR's CI is green on its head: lint, mypy strict, import contracts, migrations check,
  OpenAPI drift, Semgrep, gitleaks, pip-audit, IaC checks, prove-gates, container smoke.
- Live checks with MFA sign-in on the local stack for every screen (screenshots in the PRs). They
  found and fixed:
  - negative amounts shown as 0.00;
  - phone-width overflow;
  - failed imports that could not be retried;
  - a lost malware-refusal audit event.

## Known limitations
- **No hosted environment.** Staging and production need your approval (Gate P, #78). The S3
  bucket, KMS key and ClamAV service on AWS are not yet in the Terraform skeleton.
- **Not yet built:**
  - statutory statements (M10);
  - VAT returns and tax (M9; no filing ever without human sign-off);
  - multi-currency (M6).
- **Verification needed:**
  - VAT rates are **unverified** until a Cyprus tax professional confirms them (#93); the 3% rate
    is withheld;
  - Greek wording needs a native speaker's review.
- **Bank:**
  - no grouped matching yet (many bank lines to one ledger entry);
  - CSV mappings are API-only;
  - raw statement files are still stored in the database.
- **Documents:**
  - attaching to open items is API-only in the UI;
  - retention and disposal is a later platform job.
- **Statements:** cash-flow classification is per balance-sheet line (ADR-0013); comparatives are
  prior year only.
- **Year end:** a year with no income or expense cannot be closed; audit changes to a closed year
  need re-open, adjust and close (ADR-0014).

## Decisions and approvals needed from you
1. **Review and merge** PRs #1–#22 (#89) and #96–#105, in order.
2. **ADRs to accept or change:**
   - ADR-0012 (AWS target);
   - ADR-0013 (statements);
   - **ADR-0014 (no OPENING entry at year end: a deliberate deviation from planning doc 05)**;
   - ADR-0015 (bank imports and reconciliation);
   - ADR-0016 (document vault).
3. **New dependencies,** with licences pre-approved in the brief where listed:
   - openpyxl (MIT);
   - reportlab (BSD);
   - defusedxml (PSF);
   - boto3 (Apache-2.0);
   - the bundled Liberation Sans font (SIL OFL 1.1).
4. **Lint rule exemption:** the no-float lint gains a reasoned per-line exemption, used only for
   PDF layout sizes.
5. **Open questions:**
   - #90 other currencies;
   - #91 banks and export formats (both CAMT.053 and CSV are supported meanwhile);
   - #92 software to migrate from;
   - #93 tax professional;
   - #94 identity-provider hosting;
   - #95 pilot reviewers.

Milestone 3 (Phase 2 start: cash forecast, budgets, KPIs on the shared calculation framework)
waits for your review of this milestone.
