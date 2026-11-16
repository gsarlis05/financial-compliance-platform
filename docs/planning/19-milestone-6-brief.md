# 19 — Milestone 6 Implementation Brief: three-statement projections and rolling forecasts

Status: **IN PROGRESS** (product owner go-ahead 2026-11-12: "Continue", after the Milestone 5
report). Backlog: [08 §Phase 3](08-implementation-backlog.md). Specification:
[10](10-cfo-fpa-specification.md) §1, §2.4 and §4 (approved). Testing: [12](12-fpa-testing-and-acceptance.md) §1.

The pilot (Gate P) still waits for the owner's decisions and approval; nothing in this milestone
needs it. As in Milestone 5, the simplest sound option is taken wherever the specification leaves a
choice (owner, 2026-11-10: "continue with what is easier for now for best coding").

## 1. Business purpose
Milestones 3 and 4 answered "will we have enough cash in the next 13 weeks?" and "are we on plan?".
Milestone 6 answers the longer question: **"Where will the business be in one or two years, on
all three statements?"**
- **Fixed assets:** a register of what the business owns, with depreciation worked out for you.
- **Assumptions you can see and change:** growth, margins, costs, payment days, investment,
  borrowing, tax and dividends, month by month.
- **Three statements that always agree:** a projected income statement, balance sheet and cash flow
  statement, built from the actual balance sheet, where assets always equal liabilities plus equity
  and the cash on the balance sheet always equals the cash flow statement.
- **Rolling forecasts:** the next 12 or 24 months, refreshed as the books move, with a record of
  how good earlier forecasts were.
- **The full-year outlook:** actual months plus forecast months, clearly separated, by month,
  quarter and year; goals use it when it exists.

## 2. Rules carried from the approved specification (doc 10 §1)
- **P1:** actuals, including the opening balance sheet, come only from posted ledger entries through
  `reporting`. The projection never stores or edits actuals.
- **P2/P3:** every projected value has nature `FORECAST`; actual months are `ACTUAL`; blends have a
  cut-over date and a nature per column.
- **P4:** a projection is a calculation run: same inputs and engine version give byte-identical
  results (hash), pinned to a ledger watermark.
- **P5:** approved assumption sets and published projections never change; changes are new versions.
- **P6:** every projected line can be explained by its assumption, driver and opening balance.
- **P7 and §2.4:** Decimal throughout; each statement line is rounded to cents once per period;
  subtotals, totals, cash and retained earnings are sums of rounded lines, so the statements tie to
  the cent with no rounding plugs.
- **§4.2:** every run checks the six invariants; a run that fails one is `INVALID` and cannot be
  published.

## 3. Defaults taken (change them any time)
| Question | Default in M6 |
|---|---|
| Fixed-asset register (M6-1) | Per legal entity: asset, category, the asset account and accumulated-depreciation account, acquisition date and cost, residual value, useful life in months, method, and disposal. Methods: **straight-line** (default) and **declining balance** (rate per year). Depreciation is monthly and starts in the month after acquisition (owner-adjustable convention, stated on every schedule). Each month is rounded to cents; the last month takes the residual so the total equals cost − residual exactly. |
| Depreciation entries (M6-1) | Each month the register **prepares** one depreciation journal entry per entity as a **draft** (Dr depreciation, Cr accumulated depreciation, by asset in the description). It goes through the normal approval and posting; the register never posts by itself, and a period that already has its entry is skipped. Disposals are recorded in the register and booked by the user (the gain or loss is shown, not posted). |
| Assumption sets (M6-2) | Per entity, a named, versioned set with a lifecycle `DRAFT → APPROVED → SUPERSEDED` (no separate submit step, unlike budgets). Approval by someone with `planning.publish`. One value per driver per month over the horizon. |
| Drivers (M6-2) | Revenue per revenue line and operating costs per cost line (payroll included) as monthly amounts; "start from actuals" fills them from the same month last year, revenue grown by an optional % a year (ADR-0038). Cost of sales: gross margin %. D&A: from the register plus planned capex (useful life per capex line). Capex: amount per month. Working capital: DSO, DIO, DPO in days. Tax: effective rate on profit before tax (paid in the following year by default). Financing: new borrowing and repayments per month (or from the M3 debt schedules), interest rate. Equity: dividends (amount or payout % of last year's profit) and new share capital. Minimum cash and an optional revolving facility (limit, rate). |
| Starting a set (M6-2) | "Start from": last year's actuals (growth 0%, margins and days as observed over the trailing 12 months), or the approved budget for the year (revenue and costs as budgeted). The source of every value is recorded. |
| Engine (M6-3) | Monthly periods from the cut-over (the last closed or chosen month end) for 12, 24 or 36 months. Order exactly as doc 10 §4.1. Interest on **opening** debt (no circularity); the average-balance mode is left for later. Lines that the drivers do not cover (other receivables and payables, investments, intangibles) are held at their opening balance and listed as "held". |
| Invariants (M6-3) | The six of doc 10 §4.2, checked on every run and stored with it. A run that fails is `INVALID`, shows which invariant failed and where, and cannot be published. |
| Rolling forecasts (M6-4) | A rolling forecast is an entity setting: horizon (12 or 24 months) and the approved assumption set it uses. When the books change after the run's watermark, the run is stale; a scheduled job (as in M3-8) re-runs stale rolling forecasts as new runs. Earlier runs are kept. Accuracy: for each closed month, the forecast made 1, 3 and 6 months earlier vs the actual, for revenue, EBITDA and cash (absolute and % error). |
| Full-year outlook (M6-5) | Actual months up to the cut-over from the ledger, forecast months from the latest valid published projection; one column per month with its nature, quarter and year totals that are sums of months, and a visible divider. Goals (M4-6) use this outlook as their likely outcome when a published projection exists for the year, and say so; otherwise they keep using the budget or the run rate. |
| Screens (M6-6) | Fixed assets (register, schedule, prepared entries); Assumptions (a grid of drivers by month, start-from, approve); Projections (the three statements with a nature per column, invariants panel, explain a line, charts in SVG as before); Outlook. Excel export of the statements with a nature column (formula-safe, as in M4-2). |
| Multi-currency (M6-0, #80) | **Last, and only if confirmed.** The currency decision is still open (default: EUR only). M6-0 is built at the end of the milestone unless the owner says EUR is enough, in which case it is closed as not needed. Rates are entered or imported from a file with a source and hash; no live market data (doc 10 §13). |
| Golden model | A hand-worked 24-month projection for Demo Trading, independent of the engine, checked to the cent; **professional sign-off is an owner item**, as for the earlier golden fixtures. |

## 4. Order and approach
| # | Item | Issue | Approach |
|---|---|---|---|
| 1 | M6-1 Fixed assets | #135 | `assets` module: register, categories, schedules (straight-line, declining balance), disposals, monthly depreciation prepared as draft entries through the ledger's public interface; API, UI, audit, demo assets. |
| 2 | M6-2 Assumption sets | #136 | `projections` module: versioned assumption sets and driver values by month; start from actuals or budget; approval; immutability triggers; grid UI. |
| 3 | M6-3 Projection engine | #137 | Three-statement engine as a calc run: opening balance sheet at cut-over, the calculation order of doc 10 §4.1, rounding per §2.4, six invariants, lineage per line, publish only when valid; property tests and the golden model. |
| 4 | M6-4 Rolling forecasts | #138 | Rolling settings, staleness from the ledger watermark, scheduled re-runs, run history, accuracy metrics. |
| 5 | M6-5 Outlook and views | #139 | Full-year outlook (actual + forecast with a divider), month / quarter / year views with exact aggregation, goals use the outlook. |
| 6 | M6-6 Projection screens | #140 | Assumptions grid, statements with nature columns, invariants panel, explain a line, charts, Excel export. |
| 7 | M6-0 Multi-currency | #80 | Only if confirmed (§3). |
| 8 | M6 report | — | Evidence per acceptance criterion and owner items. |

Every item follows the established patterns: tenant-owned models with FORCE row-level security and
composite keys; a permission on every route; an audit event per change; problem+json errors and
Decimal money; OpenAPI regenerated; live checks for every screen; English and Greek; planning modules
never import the ledger (fixed assets prepare entries through the ledger's public interface only).

## 5. Acceptance criteria
- **AC-FA1** Depreciation schedules: straight-line and declining balance match hand-computed tables
  to the cent; the total equals cost − residual exactly; disposals stop depreciation.
- **AC-FA2** Prepared depreciation entries are drafts that need the normal approval; a month is
  never prepared twice; nothing is posted by the register.
- **AC-PJ1** For any valid assumption set (property tests) and on the golden model, every period
  satisfies all six invariants of doc 10 §4.2, exactly.
- **AC-PJ2** Period 1 opens on the actual balance sheet at the cut-over, line for line.
- **AC-PJ3** The golden 24-month model for Demo Trading matches to the cent (professional sign-off
  pending).
- **AC-PJ4** Re-running a projection with the same inputs gives the same hash; new postings after
  the watermark do not change a stored run.
- **AC-PJ5** An approved assumption set and a published projection cannot be changed (database).
- **AC-PJ6** A run that fails an invariant is `INVALID`, says where, and cannot be published.
- **AC-RF1** A posting marks the rolling forecast stale; the scheduled job creates a new run and keeps
  the old one; accuracy is reported for closed months.
- **AC-OL1** The outlook takes actual months from the ledger and forecast months from the
  projection; every column has its nature; quarters and the year are exact sums of months.
- **AC-UI1** Every new screen passes axe, shows nature by more than colour, and has a table
  alternative to each chart.

## 6. Risks
| Risk | Mitigation |
|---|---|
| A projection read as actual | Nature on every value and column; actual months only from the ledger; divider at the cut-over |
| Statements that do not balance, or balance only through a plug | Rounding per line (§2.4); six invariants on every run; no plug line exists; property tests over random assumption sets |
| Circular interest calculation | Interest on opening debt by default (doc 10 §4.1) |
| The register posting entries behind the user's back | It only prepares drafts through the ledger's public interface; normal approval applies |
| Scope (three L items) | One PR per issue in the order above; each PR stands alone |
