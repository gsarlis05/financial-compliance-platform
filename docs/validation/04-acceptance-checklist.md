# 4. Acceptance checklist

Prepared 2026-11-16 by the development team. **Overall status: NOT ACCEPTED. The automated
validation passes; the required professional review has not been done.**

## 4.1 Tests
| # | Test | Criterion | Result |
|---|---|---|---|
| T1 | Independent 24-month model for each scenario | Six scenarios, 24 months each, from the conventions, no platform code | **Passed** |
| T2 | Monthly income statement, balance sheet and cash flow statement | Produced for every month of every scenario, by both models | **Passed** (`results/<scenario>/*.csv`, workbook) |
| T3 | Three-statement reconciliation, every month | C1 to C10 hold (1,308 checks); engine's 8 invariants hold; workbook formulas are 0 | **Passed** |
| T4a | Depreciation | Engine = model to EUR 0.01, every month | **Passed** (largest difference 0.00) |
| T4b | Tax (current, deferred, balances, payments, losses) | as above, and the same payments | **Passed** |
| T4c | Financing (interest, debt lines, loans, facility, equity flows) | as above, and every loan figure | **Passed** |
| T4d | Working capital | as above | **Passed** |
| T4e | Capital expenditure | as above | **Passed** |
| T4f | Cash | as above | **Passed** |
| T5 | Engine against the independent model | 8,928 values within EUR 0.01 | **Passed** (all identical) |
| T6a | Edge case: losses | S2 (losses used oldest first, an expiry), S6 (a loss year and its use) | **Passed** |
| T6b | Edge case: negative cash | S2, S3, S6 (facility exhausted; negative cash stated) | **Passed** |
| T6c | Edge case: early loan repayment | S4 (with a variable rate, a bullet and new borrowing) | **Passed** |
| T6d | Edge case: changing revenues | S5 (seasonality, growth, decline, changing margin and days) | **Passed** |
| T6e | Edge case: unexpected expenses | S6 (one-off cost, non-deductible fees, refund of an instalment) | **Passed** |
| T7 | Figures worked out by hand | Every figure in `02-scenarios.md` agrees with both models | **Passed** |
| T8 | Kept up to date | `backend/tests/validation/test_package.py` fails if the engine changes any result or the results are stale | **Passed** (runs in CI) |

## 4.2 Failed tests
None.

## 4.3 Unresolved issues
| # | Issue | Owner | Status |
|---|---|---|---|
| U1 | **Professional review** of this package by a qualified independent accountant (ACA, ACCA, CPA or equivalent) with financial-modelling experience | Product owner (to appoint the reviewer) | **Open** |
| U2 | Reviewer's view on observations O1 to O6 (`03-discrepancy-report.md` §3.3) | Reviewer | Open |
| U3 | Verification of the Cyprus corporate tax rules and capital allowance rates by a Cyprus tax professional | Product owner (#154) | Open |

## 4.4 Corrective actions
| # | Action | Status |
|---|---|---|
| A1 | D1 to D7 of the discrepancy report corrected, each with a test | Done (pull requests #157 to #162) |
| A2 | Engine kept at `PENDING_PROFESSIONAL_REVIEW`, shown on every projection screen and export | Done; remains until U1 is signed |
| A3 | After the review: correct anything the reviewer finds, re-run `python -m fcp.devtools.validation`, record the signed form, and only then change the engine's status (a pull request for the product owner to approve) | Waiting for U1 |

## 4.5 Acceptance
The engine may be described as validated and production-ready only when T1 to T8 pass **and**
`05-reviewer-sign-off.md` is completed and signed by the reviewer, and the product owner records
the acceptance. Neither has happened.
