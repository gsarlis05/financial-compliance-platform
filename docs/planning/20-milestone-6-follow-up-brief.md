# 20 — Milestone 6 follow-up brief: accounting-grade projections, Cyprus tax, debt, currency foundation and professional validation

Status: **IN PROGRESS** (product owner decisions of 2026-11-15, recorded in §2). Follows the
Milestone 6 report (`docs/milestone-6-report.md`, PRs #141–#146), which stays as delivered; this
brief replaces the simplified defaults it listed for confirmation.

**Priority (owner, 2026-11-15):** accounting correctness, regulatory compliance, auditability,
financial-statement integrity and long-term scalability come before development speed. This
replaces the earlier "continue with what is easier for now" (2026-11-10) for this work.

**The projection engine is not production-ready** until the validation tests of §5 pass **and** a
qualified independent professional has reviewed and signed the sign-off package. Until then every
projection screen and export says so, and no document calls the model certified.

## 1. Purpose
Turn the Milestone 6 projections from a sound simplified forecast into a professional accounting,
tax and CFO decision-support model:
- depreciation that follows IAS 16 for actual accounting, with separate tax capital allowances;
- Cyprus corporate tax as versioned, sourced, jurisdiction-specific data: rate, loss
  carry-forwards, provisional instalments and the final balancing payment, with tax expense, tax
  liabilities and tax cash kept apart;
- real debt: several loans with their own rates, repayment structures, drawdowns, early
  repayments and variable rates, reconciling interest, principal, balances and cash;
- rolling forecasts that also react to material changes, with published versions kept immutable
  and history compared with actuals;
- goals judged against the published projection while the approved budget stays a separate
  benchmark;
- a database ready for multi-currency, with multi-currency transactions still disabled;
- a complete package for an independent professional to validate the engine.

## 2. Owner decisions (2026-11-15)
| # | Decision |
|---|---|
| D1 | Simplified forecasts: depreciation starts the month after purchase **by default**; the user can choose the commencement date and method (per capex line). |
| D2 | Actual accounting follows IFRS: under IAS 16 depreciation begins when the asset is **available for use**. |
| D3 | Accounting depreciation and **tax capital allowances** are kept separately. |
| D4 | Cyprus is the first tax jurisdiction: 15% corporate income tax from 2026; provisional tax instalments, the final balancing payment and their deadlines; tax losses carried forward (seven years from 2026) instead of no relief; tax expense, tax liabilities and cash tax kept separate; rules and deadlines configurable, versioned and per jurisdiction. |
| D5 | Interest on the **opening** debt balance each month is confirmed as the default simplified convention. Different rates, repayment structures, additional borrowing, early repayments and variable rates are supported, and interest, principal, balances and cash reconcile. |
| D6 | Rolling forecasts: recalculated hourly by default, also after material changes to financial data or assumptions, and on demand; a published forecast stays unchanged until a newly approved version is published; history is kept for comparison with actuals. |
| D7 | Goals use the latest approved, published projection as the forward-looking reference; the approved budget remains a separate benchmark; actual vs budget, actual vs forecast and projected vs goal are shown; approved goals never change when forecasts change. |
| D8 | EUR is the default functional and reporting currency in the first release; ISO 4217 codes; the database supports transaction, functional and reporting currencies, exchange rates and FX gains and losses; multi-currency transactions stay **disabled** until their full accounting treatment is implemented and tested. |
| D9 | A professional sign-off package for the 24-month golden model (§5), reviewed and signed by a suitably qualified independent professional (ACA, ACCA, CPA or equivalent, with financial-modelling experience). Nothing is represented as certified before that. Monetary reconciliation tolerance: €0.01, with documented rounding rules. |

## 3. Regulatory facts used, and their status
Rules are **data**, versioned by jurisdiction and effective date, each with its source and a
verification status. Values below are taken from published professional summaries; the primary
legal texts (Official Gazette of 31 December 2025) could not be opened from the development
environment. They are stored as **PENDING_PROFESSIONAL_VERIFICATION** and shown as such on every
screen that uses them, until a Cyprus tax professional confirms them (owner item #154).

| Rule (Cyprus, companies) | Value | Effective | Sources |
|---|---|---|---|
| Corporate income tax rate | 12.5% | tax years to 2025 | prior law (to be confirmed with the 2026 rule) |
| Corporate income tax rate | 15% | tax years from 2026 | EY Global Tax News 2026-0140; PwC Cyprus "The Cyprus Tax Reform"; ITR "Cyprus tax reform updates effective from 2026" |
| Tax loss carry-forward | 5 years | losses before the 2026 change (transition to be confirmed) | Income Tax Law s.13(1) first proviso, before amendment |
| Tax loss carry-forward | 7 years | from 2026 (the amendment replaces "five" with "seven" in s.13(1)); how it applies to earlier years' losses is **to be confirmed** | EY 2026-0140; summaries of the 2025 amending law (law number to be confirmed from the Gazette: summaries cite both 207(I)/2025 and 244(I)/2025) |
| Provisional tax | two equal instalments: 31 July and 31 December of the tax year | current | RSM Cyprus provisional tax notes (2022–2023); IBCCS "Cyprus Provisional Tax 2026" |
| Final tax (self-assessment) | balance due by 1 August of the following year | current | same |
| Underestimation charge | 10% of the shortfall when provisional taxable income is below 75% of final | current | RSM Cyprus; modelled as information only (not charged in projections) |
| Interest and penalties on late payment | vary by year | — | not modelled; projections assume payment on time |
| Capital allowances (wear and tear) rates | by asset class | — | **not seeded**: classes and rates are entered as data by the user or a tax professional; none are built in until verified |

Nothing in §3 is applied silently: every projection records the rule-set version it used, and the
explain view and the Excel export name it with its verification status.

## 4. Order and approach
One stacked PR per issue, each with full verification (make test, make lint, make security, live
UI checks), PROGRESS and pr-links updated. Database changes ship with FORCE row-level security,
composite tenant keys and guard triggers as before; reference rule data is a read-only global
table changed only by migrations.

| # | Item | Approach |
|---|---|---|
| F1 (#80) | **Currency foundation** (D8; reuses #80, narrowed) | ISO 4217 reference table and checks on every currency column; entity reporting currency (default = functional, EUR); journal lines carry transaction currency, transaction amount and the exchange rate alongside functional amounts, constrained for now to transaction = functional currency at rate 1; exchange-rate table (date, pair, rate, source, hash) with no live feed; an entity setting that keeps multi-currency **disabled** (the API refuses foreign-currency entries); FX gain/loss lines reserved in the taxonomy. ADR. |
| F2 (#147) | **Tax rule sets** (D4) | `taxrules` module: jurisdiction rule sets by effective date (rate; loss carry-forward years by loss year; provisional instalment dates and shares; final payment deadline; sources; verification status). Cyprus seeded per §3. Read-only global reference data; projections pin the version used. ADR. |
| F3 (#148) | **Depreciation commencement and capital allowances** (D1–D3) | Register: available-for-use date (IAS 16 commencement, default the acquisition date) and an entity policy for the first month (pro rata by days, or from the next month); method per asset (straight-line, declining balance). Projection capex: commencement (default the month after spend, or a chosen month) and method per capex driver. Tax capital allowance classes and rates as data (per jurisdiction, versioned, none seeded), allowance schedules per asset kept separately from accounting depreciation. |
| F4 (#149) | **Debt instruments in projections** (D5) | Existing loans from the M3 debt register and new loans in the assumption set: amount, drawdown month, term, fixed or variable rate (a rate path by month), repayment structure (annuity, equal principal, bullet, interest-only periods), early repayments by month; opening-balance interest by default. Per-loan roll-forward and current/non-current split (principal due within 12 months). New invariant: per-loan roll-forwards tie to interest expense, principal cash flows and balances. Engine version 2. |
| F5 (#150) | **Corporate tax in projections** (D4) | Taxable profit = profit before tax + accounting depreciation − capital allowances (± other permanent adjustments as drivers); loss pool by vintage with expiry from the rule set; annual tax by tax year, accrued monthly on a year-to-date basis; provisional instalments on their dates from the projected tax of the year; the final balancing payment by its deadline; tax payable or receivable as the balance; current tax expense, tax liability and tax cash reported separately; deferred tax on fixed-asset temporary differences (IAS 12), with a deferred tax asset on losses recognised only if the entity's setting says so (recognition is a judgement). New invariants: tax roll-forward (opening + expense − payments = closing) and the loss pool roll-forward. Engine version 2. |
| F6 (#151) | **Rolling forecasts: material changes and history** (D6) | Event-driven re-runs: a newly approved assumption version, or postings above an entity materiality threshold (default: any posting), make the next scheduled pass (every 15 minutes) re-run; otherwise hourly. Published runs stay the reference until a newer run is approved and published. Compare any past run with actuals line by line. |
| F7 (#152) | **Goals and benchmarks** (D7) | Each goal evaluation shows three outcomes side by side: actual, projected (published projection) and budget benchmark; screens for actual vs budget, actual vs forecast and projected vs goal; a test that new projections never change an approved goal. |
| F8 (#153) | **Professional validation package** (D9) | `docs/validation/`: an independent 24-month model as a formula workbook (evaluated independently of the engine), monthly statements and full monthly reconciliation, validation of depreciation, tax, financing, working capital, capex and cash; scenarios for losses, negative cash, early repayment, changing revenue and unexpected expenses; automated comparison with the engine at €0.01; a discrepancy report; an acceptance checklist; a reviewer sign-off form. The engine stays "pending professional review" until signed. |

## 5. Validation criteria (engine production readiness)
- **V1** The independent model and the engine agree to €0.01 on every line, every month, every
  scenario; every difference is listed with its cause.
- **V2** Every month of every scenario passes the reconciliations: balance sheet balances; cash
  flow statement ties to balance-sheet cash; retained earnings, fixed assets, each loan, tax and
  the loss pool roll forward.
- **V3** Depreciation, capital allowances, tax (including losses and instalments), financing,
  working capital, capex and cash are each checked against hand-derivable figures.
- **V4** The acceptance checklist has no failed or unresolved item, or each is accepted in writing
  by the owner.
- **V5** A qualified independent reviewer has signed the package. Only then may the engine be
  marked production-ready (a recorded flag, shown on screen).

## 6. Rounding rules (documented for V1)
- Every statement line is rounded to cents (half-up) once per month; subtotals, totals, cash and
  retained earnings are sums of rounded lines (doc 10 §2.4). No plug line exists.
- Interest per loan per month = round(opening balance × annual rate / 12) (or per the loan's day
  count where the register defines one). Depreciation per asset per month is rounded once; the
  last month takes the remainder. Annual tax is rounded once per tax year; monthly accruals are
  year-to-date differences, so they add up to the annual figure exactly. Provisional instalments
  are rounded once each; the final payment takes the remainder.
- Monetary reconciliation tolerance: €0.01 per line per month for comparisons of independently
  computed figures; internal invariants must hold exactly.

## 7. Risks
| Risk | Mitigation |
|---|---|
| Tax rules applied wrongly | Rules as sourced, versioned data with a verification status shown everywhere; professional verification is an owner item; every run pins the version |
| Changing the engine invalidates earlier runs | Engine version 2 is a new version; stored version-1 runs stay reproducible |
| Multi-currency half-built | Columns and constraints ready, the feature refused by the API until it is fully implemented and tested |
| Validation that is not independent | The reference model is a formula workbook evaluated separately from the engine's code |
| Scope | One PR per item in the order above; each stands alone |
