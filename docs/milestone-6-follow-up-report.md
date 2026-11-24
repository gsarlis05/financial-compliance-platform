# Milestone 6 follow-up report (owner decisions of 2026-11-15)

Date: 2026-11-16. Brief: `docs/planning/20-milestone-6-follow-up-brief.md`. Every item is a
separate pull request stacked on the previous one, each with its own tests, documentation and
ADR. Nothing is merged, deployed or applied; merging is for the product owner.

**The projection engine is not production-ready and is not certified.** Its validation tests pass,
but the professional review the owner requires has not been done (§4).

## 1. What was delivered
| Item | Owner decision | Pull request | What changed |
|---|---|---|---|
| F1 Currency foundation | D8 Currency | #155 (closes #80) | ISO 4217 table; transaction, functional and reporting currencies in the database; exchange-rate table; FX gains/losses prepared; multi-currency transactions refused by the database until enabled (ADR-0042) |
| F2 Tax rule sets | D4 Tax | #156 (#147) | Corporate tax rules as versioned, sourced, jurisdiction-specific data; Cyprus seeded (12.5% to 2025, 15% from 2026; losses 5 then 7 years; instalments 31 July and 31 December; balance by 1 August), all **pending professional verification** (ADR-0043) |
| F3 Depreciation and capital allowances | D1-D3 Depreciation | #157 (#148) | IAS 16 commencement from the available-for-use date (pro rata, next month or full month); method selectable; tax capital allowances kept separately, with versioned classes and no built-in rates; projections: commencement and method for new capex (default: the month after) (ADR-0044) |
| F4 Debt and interest | D5 Debt | #158 (#149) | Loans one by one: annuity, equal principal, bullet; interest-only months; variable rates; early repayments; extra borrowing; loans from the debt register; interest on the opening balance (confirmed default); seventh invariant: debt reconciles every month (ADR-0045) |
| F5 Corporate tax in projections | D4 Tax | #159 (#150) | Current and deferred tax, losses by the year they arose (carry-forward and expiry), provisional instalments, final payments and refunds, from the versioned rules; income tax separate from VAT; eighth invariant: tax reconciles (ADR-0046) |
| F6 Rolling forecasts | D6 Rolling | #160 (#151) | Re-run at once on material changes (approved assumptions, a closed month, postings above a materiality threshold), otherwise at the regular interval (hourly by default), or on demand; the published projection stays the reference until a newer one is published; any past projection compared with actuals line by line (ADR-0047) |
| F7 Goals and benchmarks | D7 Goals | #161 (#152) | The published projection is the forward reference and the approved budget a separate benchmark; actual vs budget, actual vs forecast, projected vs budget and projected vs goal; goals never change by themselves (ADR-0048) |
| F8 Validation package | D9 Validation | #162 (#153) | Independent 24-month model, six scenarios with the requested edge cases, monthly statements, three-statement reconciliation every month, comparison at EUR 0.01, discrepancy report, acceptance checklist, reviewer sign-off form (`docs/validation/`) |

## 2. Issues found and corrected
Building the independent figures found real defects, now corrected with tests (details in
`docs/validation/03-discrepancy-report.md` §3.2):
- the old engine paid out the **VAT** balance as if it were income tax at the start of each year,
  and charged tax at a flat effective rate with no losses or instalments (corrected in F5);
- tax losses could carry fractions of a cent; a recognised deferred tax asset on losses could
  create a liability the books never had (F5);
- with a published projection, a goal's comparison "against budget" was really against the
  projection (F7);
- the demo left a pro-rata December depreciation charge unposted (F3);
- one validation scenario's opening balance sheet did not balance (the model now refuses this).

## 3. Validation results
Six 24-month scenarios: base golden model, losses carried forward, negative cash and the credit
facility, loans with a variable rate and an early repayment, changing revenues and working
capital, unexpected expenses with capital allowances and deferred tax.
- 8,928 statement values, 432 loan figures and 21 tax payments compared with the independent
  model: **all identical to the cent** (tolerance EUR 0.01; rounding rules R1 to R5).
- 1,308 reconciliation checks of the independent model and the engine's eight invariants hold in
  every month; the workbook's live reconciliation formulas, recalculated in LibreOffice, are 0.
- Figures worked out by hand for every scenario agree.
- A test fails the build if any engine change alters a result, and a negative control proves a
  2-cent difference is caught.

Limit stated in the package: both models come from the same development team, so agreement
shows that the engine does what the conventions say, not that the conventions are right; that is
the professional reviewer's task.

## 4. Open items for the product owner
| # | Item | Why it matters |
|---|---|---|
| 1 | Appoint a qualified independent reviewer (ACA, ACCA, CPA or equivalent, with financial-modelling experience) to review `docs/validation/` and sign `05-reviewer-sign-off.md` | Required before the engine can be called validated or production-ready (D9); seven observations (O1 to O7) need their judgement |
| 2 | Cyprus tax professional to verify the tax rule sets and provide capital allowance (wear and tear) rates (#154) | Rules stay "pending verification" on every screen until then; projections with capex have no tax allowances until classes are set up (observation O1) |
| 3 | Review and merge the stacked pull requests #155 to #162 in order | Each needs the owner's approval; CI is green on those already pushed |

## 5. Known limitations (unchanged by this work, stated in the ADRs)
Multi-currency transactions are disabled; projections assume calendar tax years and a cut-over at
a month end (the validation scenarios use year ends); late-payment interest, penalties and the
underestimation charge on provisional tax are not modelled; balancing allowances on disposal are
not modelled; loan fees, covenants and day-count interest are not in projections.
