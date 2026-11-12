# ADR-0039: The three-statement projection is a pure engine run as a calculation run
Status: **Proposed** (M6-3; awaiting product owner review in PR) · Date: 2026-11-12

## Context
Doc 10 §4 asks for a projected income statement, balance sheet and cash flow statement that start
from the actual balance sheet, follow a fixed order of calculation (§4.1), and always satisfy six
invariants (§4.2), with every value reproducible (P4), labelled FORECAST (P2) and explainable (P6).
Rounding must not need a plug line (§2.4).

## Decision
- **A pure engine** (`projections/engine.py`): `project(EngineInput) -> Projection`, no database.
  Its input is plain data: the cut-over, the months, the opening balance sheet by taxonomy line,
  the approved set's driver values, the depreciation of the registered assets by month and the
  months that start a fiscal year.
- **Order per month** exactly as doc 10 §4.1: revenue, cost of sales from the gross margin on sales
  and services, operating costs, depreciation (register + new capex straight-line over its life,
  from the month after it is spent); interest on the **opening** debt and credit facility (no
  circularity); tax on a positive profit before tax (no loss relief), accrued and paid in the first
  month of the next fiscal year; working capital from days over the days in the month; debt
  (borrowing non-current, repayments from current debt first, capped at what is owed); equity;
  cash flow (indirect); then the credit facility drawn up to its limit to keep the minimum cash and
  repaid when cash is above it. Lines the drivers do not cover are held at their opening balance.
- **Rounding:** each statement line is rounded to cents once per month; totals, cash and retained
  earnings are sums of rounded lines. There is no plug line.
- **Six invariants** checked on every run: the balance sheet balances; the cash flow's opening and
  closing cash equal the balance sheet's; retained earnings roll forward by net income less
  dividends; each month opens on the previous closing (and month 1 on the actual balance sheet);
  the roll-forwards of fixed assets, debt, working capital and share capital tie to the cash flow;
  quarter and year totals are sums of their months. A failure also records
  `<invariant>@<month>` so the run says where; the framework marks it INVALID and it cannot be
  published.
- **As a calculation run** (kind `PROJECTION`, `projections/runs.py`): the account mapping, the
  register's depreciation plan and the fiscal-year starts are pinned in the run's inputs; the
  opening balance sheet is read from the ledger at the run's watermark through `reporting`; the
  approved set never changes. Income and expense balances not yet closed at the cut-over go to
  retained earnings; an unmapped account with a balance is refused before any run is recorded.
- **Outputs:** the opening balance sheet as ACTUAL; every monthly line as FORECAST with lineage to
  its driver (`assumption_set:<id>:<driver>:<month>`), the asset register or the formula; quarter
  and year buckets of whole months from the first projected month.

## Consequences
- The engine is property-tested over random assumption sets and balanced openings (all six
  invariants hold exactly) and checked against a 24-month golden model worked out in closed form;
  professional sign-off of the golden model is an owner item.
- Interest on average balances, loss carry-forward, VAT balances, dividends as a payout %, and
  loans from the M3 schedules as financing inputs are left for later; each is a change to the pure
  engine and a new engine version.
- Quarters and years follow the projection's months, not the fiscal calendar, until M6-5's outlook.
