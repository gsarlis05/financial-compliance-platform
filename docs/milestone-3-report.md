# Milestone 3 report: calculation framework and 13-week cash forecast

Status: **complete, awaiting product owner review** (PRs #108–#117, stacked after Milestone 2;
each is reviewable on its own). No environment exists beyond local development and CI, and no
migration has been applied anywhere else. Brief:
[planning doc 16](planning/16-milestone-3-brief.md); specification: planning docs 10 and 12. Both
docs are on the planning branch (PR #1), which is not yet merged.

## What you can do now
On top of Milestones 1 and 2, you can:
- **See 13 weeks of cash.** **Cash & planning → Cash forecast** shows opening cash and, week by
  week, money in, money out and closing cash. It also shows headroom against your minimum cash,
  liquidity including facilities, and the first day cash would fall short. Every amount is
  labelled *actual*, *committed*, *expected* or *forecast*, in text and line style, never colour
  alone.
- **Drill into any week:** see its flows, then from a flow to the invoice, scheduled payment or
  manual item behind it.
- **Ask "what if?"**, for example "this customer pays 60 days later", "suppliers cost 10% more",
  or "a one-off payment". The change shows week by week as a *hypothetical* line. Nothing is
  saved, and the forecast itself never changes.
- **Keep it current:** the forecast says when it is out of date (new postings, changed open items,
  commitments or settings) and why. You can run it again; earlier forecasts are kept. Accuracy is
  tracked as weeks pass.
- **Record what you already know:**
  - recurring obligations (rent, payroll, subscriptions);
  - loans, with full instalment schedules (annuity, linear, bullet, interest-only then annuity;
    ACT/360, ACT/365, 30/360);
  - overdraft and revolving facilities;
  - tax payments;
  - non-working days;
  - manual items with a reason.

  Changes keep their history.
- **See how late each customer pays** (observed over the last 12 months), and override it where
  you know better.

Try it with `make demo` ([demo script](demo.md)). Its 18 steps now end with a 13-week forecast for
Demo Trading. See the user guides: [cash forecast](user-guide/cash-forecast.md),
[obligations, loans and tax](user-guide/obligations-and-loans.md) and
[payment behaviour](user-guide/payment-behaviour.md).

## Items
| Item | PR | What |
|---|---|---|
| M3-1 Calendar | #108 | ISO weeks (incl. week 53), fiscal years in any month, business days with holiday data, 13-week buckets, dated allocation (never pro-rated); M3 brief |
| M3-2 Metrics core | #109 | natures as types (no `+` between actual and plan; `blend()`), calculation runs with pinned inputs, input/output hashes, lineage, immutability; actuals read at a pinned watermark (ADR-0017) |
| M3-3 Expression language | #110 | hand-written, sandboxed, Decimal, unit-typed formulas; safe division (not meaningful, never 0 or ∞); limits; 14,000 fuzzed cases per run (ADR-0018) |
| M3-4 Obligations and loans | #111 | versioned recurring obligations and loans, facilities, holidays, schedule generator checked against reference tables (ADR-0019) |
| M3-5 Tax payment calendar | #112 | manual, versioned tax payments, committed or expected; no built-in dates (decision #93) |
| M3-6 Payment behaviour | #113 | observed days late per customer (amount-weighted, 12 months, minimum 3 invoices), override |
| M3-7 13-week forecast engine | #114 | `cashflow` module; inputs snapshotted into each run; weekly buckets, minimum cash, liquidity, shortfall; demo golden file (ADR-0020) |
| M3-8 Re-runs, history, accuracy | #115 | freshness by comparison, scheduled refresh job, history, forecast-vs-actual accuracy (ADR-0021) |
| M3-9 What-ifs | #116 | timing shift, % change, one-off; HYPOTHETICAL; never saved; delta per week |
| M3-10 Cash dashboard | #117 | chart with nature encoding, weeks table, drill-down, what-if panel, history, accuracy |

## Acceptance criteria (brief §5; doc 12 §4.1–4.2)
| AC | Evidence |
|---|---|
| AC-M3-1 ISO week 53, leap days, any fiscal start, business-day conventions, contiguous buckets, no pro-rating | `tests/calendar/test_calendar.py` (property tests) |
| AC-CF1 every value has a nature (DB, API schema, types) | DB `NOT NULL` + check constraint; `tests/metrics/test_nature.py` checks the OpenAPI schema; the dashboard shows the nature on every row |
| AC-CF2 actual + plan without `blend()` fails type checks and at runtime | `tests/metrics/test_nature.py` runs **mypy** on a snippet and asserts the error, and checks `NatureMixError` |
| AC-CF3 re-running reproduces the output hash | `tests/metrics/test_calc.py` (also after new postings); `tests/cashflow/test_forecast.py` (after new postings and manual items); the demo reproduces its forecast |
| AC-CF4 lineage for every value; explain API | `calc-runs/…/explain`; forecast flows trace to open items, schedules and manual items (`test_forecast.py`); dashboard drill-down |
| AC-CF5 evaluator rejects unknown functions, unit mismatches and oversize input; fuzzing ≥ 10k never crashes; division by zero is not meaningful | `tests/metrics/test_expr.py`: 10,000 + 2,000 + 2,000 fuzzed cases per CI run; 100% line and branch coverage |
| AC-CW1 opening = cash accounts; unreconciled warning | `tests/cashflow/test_forecast.py`; the demo's opening 371,514.38 equals the reconciled bank balance |
| AC-CW2 AR dated due + days late (or override); AP by policy; obligations, debt, tax and manual items with their nature | `tests/cashflow/test_forecast.py`, `tests/registers/test_behaviour.py`, `test_commitments.py` |
| AC-CW3 ISO weeks; dated, never pro-rated; Σ buckets = Σ flows | engine invariant, checked on every run; `tests/cashflow/test_engine.py` (300 property cases against an independent reference) |
| AC-CW4 closing = opening + net; opening(t+1) = closing(t); shortfall flags; first shortfall date | the same reference tests, plus a hand-worked example |
| AC-CW5 matches the signed-off golden workbook to the cent | **Pending sign-off.** `tests/devtools/golden/demo_cash_13w.json` is marked `signed_off: false`; every week is recomputed independently from the run's stored inputs in the demo test |
| AC-CW6 a posting or reconciliation marks the forecast stale; a new run follows; history; accuracy | `tests/cashflow/test_tracking.py` (posting, manual item, settings; refresh job; history; accuracy) |
| AC-CW7 what-if labelled HYPOTHETICAL, never saved over the base, delta per bucket | `tests/cashflow/test_whatif.py` (the "customer pays 60 days later" example, hand-computed; history unchanged) |
| AC-CW8 debt schedules match reference tables (annuity, linear, bullet; ACT/360, ACT/365, 30/360) | `tests/registers/test_schedules.py`: tables computed separately with exact fractions; 200,000 at 6.5% over 30 years gives the published 1,264.14 |

## Database changes (Milestone 3)
| Module | Migrations | Content |
|---|---|---|
| metrics | 0003–0004 | calculation runs, results, lineage; triggers (finished runs only become stale or published; results append-only; nothing deleted) |
| registers | 0005–0009 | recurring obligations, loans and facilities, holidays (versioned, same-entity keys, version guard); tax payments; customer days-late override |
| cashflow | 0001–0003 | forecast settings, manual items; `cashflow_forecast_tenant_ids()` (IDs only) |

Every new table has FORCE row-level security and composite tenant keys. Every migration was
reversed and re-applied locally, and is listed in its PR.

## Security controls added
- **Formulas cannot run code.** The expression language is hand-parsed, with no `eval` and no host
  language. It has size and depth limits, and is fuzzed in CI.
- **Calculations are evidence.**
  - Runs record their inputs and hashes, and the database refuses any change to a finished run
    other than marking it stale or published. Results are append-only.
  - Obligation, loan and tax versions can only be superseded.
- **Least privilege.**
  - Planning code never imports the ledger (import contract).
  - The refresh job finds workspaces through an ID-only function, and acts with a real user's
    current permissions.
  - Viewing and what-ifs need read permissions only.
- **No unverified facts.** No tax dates or public holidays are built in.

## Quality
Measured on 2026-11-04 on the M3 branches (`make test`, fresh database):
- Backend: **1,067 tests pass**; **97.0%** line coverage overall. The new engines are at 95–100%.
- Frontend: **42 tests**, including axe on every new screen; ESLint strict, `tsc`, build.
- Every PR's CI is green on its head: lint, mypy strict, import contracts, migrations, OpenAPI
  drift, Semgrep, gitleaks, pip-audit, IaC, prove-gates, container smoke.
- **Live checks** with MFA sign-in on the local stack for every screen, on the demo data. They and
  the tests found and fixed:
  - a recurrence skip-ahead that missed occurrences (property test);
  - read-only users unable to see whether a forecast is current (permissions test);
  - a what-if request rejected because of an empty amount (live check);
  - table action cells and hidden headers that widened pages on phones (live check);
  - a chart name merged with its description, and a heading-order issue (axe).

## Known limitations
- **AC-CW5 needs sign-off** of the golden forecast by a finance professional.
- **Accuracy** compares total net cash only. Categories need categorised bank movements.
- **Forecast inputs are simplified:**
  - disputed invoices are left out (with a warning);
  - overdraft interest is not modelled;
  - loans with irregular first periods or fees are not supported.
- **What-ifs are not stored.** Saved scenarios, rate changes and new debt come with the scenarios
  module (M5).
- **The refresh job** is documented for AWS (EventBridge → ECS every 15 minutes) but not created.
- **Greek wording** needs a native speaker's review.

## Decisions and approvals needed from you
1. **Review and merge**, in order:
   - PR #1 (the planning documents Milestone 3 relies on, including docs 10 and 12);
   - the earlier stacks (#2–#22, #96–#107);
   - #108–#117 and this report.
2. **ADRs to accept or change:**
   - **ADR-0017:** runs pin their inputs; actuals are read at a watermark.
   - **ADR-0018:** our own formula language instead of DMN/FEEL.
   - **ADR-0019:** loan conventions, including how 30/360 is counted, interest rounding and
     accrual dates.
   - **ADR-0020:** forecast rules. Please confirm three of them:
     - disputed items are left out;
     - payments before the as-of date are taken as paid;
     - overdue tax is kept in week 1.
   - **ADR-0021:** freshness by comparison; the refresh job acts as the last requester.
3. **Choices to confirm (M3-6):** days late are amount-weighted, early payment counts as negative,
   and the minimum sample is 3 invoices.
4. **Sign-offs:**
   - the golden 13-week forecast (AC-CW5);
   - verified Cyprus tax due dates and public holidays (decision #93), so templates can be
     offered;
   - Greek wording.
5. **AWS (only with your approval):** the scheduled refresh task, together with the earlier S3,
   KMS and ClamAV items.
6. **No new dependencies.** Milestone 3 adds none: the chart is SVG drawn in React, although doc 10
   names Apache ECharts.

Milestone 4 (budgets and variance, KPIs and goals on the same framework) waits for your review of
this milestone.
