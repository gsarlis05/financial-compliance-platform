# 1. Scope and method

## 1.1 What is validated
The projection engine (`backend/src/fcp/modules/projections/engine.py`, engine version 3, with
`debt.py` for loans and `tax.py` for corporate tax), which turns an opening balance sheet and an
approved assumption set into 24 monthly income statements, balance sheets and cash flow
statements. Specifically (owner's request, items 1 to 8):

1. an independently calculated 24-month model for each scenario;
2. monthly income statement, balance sheet and cash flow statement (`results/<scenario>/`);
3. a full reconciliation of the three statements for every month (§4);
4. validation of depreciation, tax, financing, working capital, capital expenditure and cash
   (`results/summary.md`, "By area");
5. a comparison of every line of every month with the engine;
6. edge cases: losses, negative cash, early loan repayments, changing revenues, unexpected
   expenses (`02-scenarios.md`);
7. a discrepancy report (`03-discrepancy-report.md`);
8. an acceptance checklist (`04-acceptance-checklist.md`).

**Not in scope** (stated with every projection, see the ADRs): the database layer that loads
inputs from the books (covered by the platform's automated tests, not by this package);
declining-balance depreciation of new capital expenditure (covered by unit tests); cut-overs
that are not a calendar year end; non-calendar tax years; multi-currency (disabled, ADR-0042);
late-payment interest, penalties and the underestimation charge on provisional tax; balancing
allowances on disposal. The correctness of the **Cyprus tax rules themselves** is a separate item
for a Cyprus tax professional (#154): this package checks that the engine applies the rules it is
given, using rule sets defined in each scenario.

## 1.2 The conventions (the specification both models follow)
From doc 10 §4 (the order of calculation), ADR-0040 (rolling), ADR-0044 (depreciation and
allowances), ADR-0045 (loans) and ADR-0046 (tax):

| Area | Convention |
|---|---|
| Revenue, costs | As assumed per line and month; cost of sales = (sales + services) x (1 - gross margin) |
| Depreciation | Registered assets: their schedule. New capex: straight-line over its life, a full month from `capex_start` months after the month of spend (default 1, the month after); the last month takes the remainder |
| Interest | On the **opening** balance of the month: other debt at the interest rate, the credit facility at its rate, each loan at its rate for the month; rounded per item |
| Loans | Annuity re-worked each month on the opening balance and months left; equal principal = balance / months left; bullet at maturity; interest-only months first; the last month repays the rest; drawdowns, repayments and early repayments at the month end; current portion = scheduled principal of the next 12 months (IAS 1.69) |
| Other debt | New borrowing is non-current; repayments reduce current debt first and are capped at what is owed |
| Tax | Taxable profit = PBT + depreciation - capital allowances + tax adjustments; current tax year to date on (taxable - usable losses), never negative, at the year's rate; losses by the year they arose, used oldest first, expiring after the carry-forward of their year; provisional instalments bring the year's payments to their cumulative share of the year's tax as projected at that month (annualised), never negative; the final balance (or refund) on the final date; the opening balance owed on the previous year's final date. Deferred tax at the year's rate on (allowances - depreciation of the same assets) and, if recognised, on losses |
| Working capital | Receivables = revenue x DSO / days in the month; inventory and payables = cost of sales x DIO (DPO) / days in the month |
| Equity | Retained earnings + net income - dividends; share capital + issues |
| Cash | Indirect method; then the credit facility is drawn (up to its limit) to keep the minimum cash, or repaid when cash is above it. Cash may go negative when the facility is exhausted: the projection then says so for each month |
| Held lines | Intangibles, investments, other receivables and payables, VAT and other taxes, share premium stay at their opening balance |

## 1.3 Rounding rules and tolerance
- **R1** Every amount is rounded to cents, half up (EUR 0.005 -> 0.01), once, where it is first
  calculated: each revenue and cost line, each depreciation, interest, tax, working-capital and
  loan amount.
- **R2** Subtotals and totals (revenue, gross profit, EBITDA, EBIT, profit before tax, net
  income, every cash flow subtotal, every balance) are sums of rounded amounts and are never
  rounded again, so the statements tie exactly with no balancing figure.
- **R3** Tax to date is rounded once (R1); a month's tax is the change in the rounded tax to
  date, so a year's tax equals the rounded tax on the year's taxable profit.
- **R4** Rates are applied unrounded (6% a year = 0.5% a month exactly); annuity payments use the
  exact formula and are then rounded to cents.
- **R5** Balances roll forward by adding rounded movements; nothing is recomputed from rates.
- **Tolerance:** two values agree when they differ by at most **EUR 0.01** (owner decision). In
  this package every compared value is in fact identical to the cent (`results/summary.md`,
  "Exactly equal").

## 1.4 Reconciliation checks (every month)
The independent model checks its own statements (C1 to C10, `results/<scenario>/reconciliation.csv`);
the engine checks its eight invariants; the workbook repeats the main ones as Excel formulas.

| Check | Meaning |
|---|---|
| C1 | Assets = liabilities + equity |
| C2 | The cash flow statement's opening and closing cash equal the balance sheet's |
| C3 | Retained earnings roll forward by net income less dividends |
| C4 | Fixed assets roll forward: cost by capex, accumulated depreciation by the charge |
| C5 | Debt rolls forward by borrowing, repayments and the facility |
| C6 | Working-capital movements in the cash flow equal the balance-sheet changes |
| C7 | Income tax payable rolls forward by current tax less payments; deferred tax by its charge |
| C8 | Each loan: opening + drawdowns - principal - early repayment = closing; 0 <= current portion <= closing |
| C9 | Net income = profit before tax - current tax - deferred tax |
| C10 | At each year end, tax losses: before + arising - used - expired = after |

## 1.5 Independence, and its limits
- The independent model was written from the conventions above, not by copying the engine's
  code; it is a single file in a different structure that imports nothing from the platform and
  needs only the Python standard library, so it can be run and read on its own.
- The two models read the same scenario files; the harness compares every statement line of every
  month, every loan figure (interest, principal, early repayment, drawdown, closing, current
  portion) and every tax payment.
- The workbook's reconciliation formulas were recalculated by LibreOffice (a third
  implementation of the arithmetic): every check is 0.
- **Limit:** both models were written by the same development team. Agreement shows that the
  engine computes what the conventions say; it cannot show that the conventions are right for a
  given business, or that both share no misreading of a convention. That is what the hand-worked
  figures (`02-scenarios.md`) and the professional review are for.

## 1.6 The professional review still required (owner decision D9)
A suitably qualified independent professional should: review the conventions (§1.2) for
appropriateness under IFRS (IAS 1, 7, 12, 16) and Cyprus tax practice; re-perform the hand-worked
figures and a sample of months in the workbook; review the observations in the discrepancy
report; and complete `05-reviewer-sign-off.md`. Until then the engine must not be described as
validated, certified or production-ready.
