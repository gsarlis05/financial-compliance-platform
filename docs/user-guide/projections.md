# Projections

Projections show where the business is heading over the next one to three years, on the income
statement, balance sheet and cash flow statement. They start from your actual books and from
assumptions you can see and change. Every projected figure is a forecast and is labelled as one.

## Assumptions
Open **Cash & planning → Assumptions**.

1. **Start a set.** Give it a name, choose the last actual month (the cut-over) and a horizon of
   12, 24 or 36 months, and choose where to start from:
   - **Last year's actuals:** revenue and costs repeat the same month of the last 12 months, with
     revenue grown by the % a year you enter. Gross margin, the days customers take to pay (DSO),
     stock days (DIO), the days you take to pay suppliers (DPO) and the interest rate are taken
     from your books. Where the books cannot tell, the value is 0.
   - **The approved budget:** revenue, costs and margin from the budget for the months it
     covers; the last 12 months for the others.
   - **Empty.**
2. **Change what you expect to be different.** Each row is a driver, each column a month. Hover
   over a value to see where it came from; values you entered are shown in bold. **Fill right**
   copies a row's first month to all months. Select **Save changes**.
3. **Approve.** An approved set never changes. To change it, select **Revise as a new version**:
   you get a draft copy, and when you approve it the earlier version is marked superseded.

## Loans
Open a set and use **Loans** to project each loan on its own:
- **Add the loans of the debt register** brings every drawn loan of the register with what is
  still owed at the cut-over, its rate and how it is repaid.
- Or add a loan yourself: an **existing** loan (what is owed at the cut-over) or a **new** one
  (the amount and the month it is drawn), with its rate, repayment (level payments, equal
  principal, or all at the end), the repayment months and any interest-only months.

Each loan then has three rows in the grid: its **rate** for each month (change it for a variable
rate), **early repayments** and **extra drawdowns**. Interest is worked out on what is owed at the
start of each month; repayments and drawdowns happen at the month end. An early repayment lowers
the later payments and keeps the end date. The part of each loan due within 12 months is shown as
short-term debt. Debt in your books that these loans do not cover is projected with the
borrowing, repayment and interest-rate rows.

## Corporate tax
Corporate income tax is worked out from the **tax rules** of the entity's country for each tax
year (see *Tax rules* below); the rule sets used are listed in the set's **Corporate tax** section
with their verification status. In that section enter the tax position at the cut-over:
- **unused tax losses** brought forward, by the year each loss arose (each can be used for the
  number of years the rules of that year allow; the oldest are used first);
- **provisional tax already paid** for the tax year of the cut-over;
- whether to **recognise a deferred tax asset on unused losses**: a judgement under IAS 12.34,
  only when future taxable profit to use them is probable. A deferred tax asset already in
  your books counts as the asset on the losses brought forward; any rest is recognised (credited
  to profit) in the first projected month. The projection then shows the asset being used, and
  any asset on new losses.

The projection then shows, every month:
- **current tax**: tax on taxable profit to date (profit before tax + depreciation − capital
  allowances + the **tax adjustments** row: non-deductible costs as positive amounts, non-taxable
  income as negative), after usable losses, at the year's rate; each month's charge is the change;
- **deferred tax**: on capital allowances that differ from the depreciation of the same assets,
  and on losses if recognised;
- **payments**: provisional tax on the rules' dates (each bringing the year's payments to its share
  of the year's tax as projected at that month), the final balance (or refund) on the final date,
  and the balance owed for earlier years on its due date;
- on the balance sheet, **income tax payable** (a receivable if negative) and **deferred tax**
  separately from VAT and other taxes, which stay at their balance at the cut-over.

Tax years must be calendar years. Late-payment interest, penalties and the charge for
underestimating provisional tax are not modelled. The figures are a projection, not tax advice,
and the rules were checked by you on 27/11/2026, not verified by a tax professional.

## Running a projection
With an approved set, open **Cash & planning → Projections**, choose the set and select **Run**. It starts
from your actual balance sheet at the cut-over, read from the posted books, and works out each
month in a fixed order: income statement, interest on the debt at the start of the month,
corporate tax, receivables, stock and payables from the days, fixed assets, debt, equity, the cash flow
statement, then the credit facility to keep the minimum cash.

Every run checks that the three statements agree: the balance sheet balances, the cash on it equals
the cash flow statement, retained earnings move only by profit and dividends, each month starts
where the last ended, quarters and years add up, each loan, the interest and the debt lines
reconcile, and the tax expense, tax balances, payments and losses reconcile. A run that fails a check is marked
**invalid**, says which check failed in which month, and cannot be published. Lines the
assumptions do not cover (intangibles, investments, other receivables and payables) stay at their
opening balance. If an account with a balance is not mapped to a statement line, map it first.

### Reading a projection
- **Natures.** Every column says **Actual** (the opening balance sheet, from your books) or
  **Forecast**, in words as well as by its border style. Show it by month, quarter or year.
- **Checks.** The eight checks are listed with **holds** or **fails**; a failed check names the month
  where it failed, and such a projection cannot be published.
- **Explain a line.** Select any figure to see where it comes from: the assumption and how it is
  used, the fixed-asset register, your books, or which other lines it is worked out from.
- **Chart.** Cash at the end of each period; the balance-sheet table holds the same figures.
- **Publish.** A valid projection can be published (with planning publish permission). The
  outlook and goals use the latest published projection.
- **Against actuals.** Any projection, published or not, can be compared with the posted books
  for its months that have closed: each income statement line and the month-end cash, as
  forecast, actual, and the difference (actual − forecast), for all closed months together or
  one month at a time.
- **Export to Excel.** One sheet per statement, with a row stating the nature of each column and a
  note that the figures are a projection, not actual results.

## Rolling forecast
A rolling forecast looks at the next 12 or 24 months from the end of the last full month, and
moves on by itself. Set it up once at the bottom of **Cash & planning → Projections**: choose an
assumption set and the horizon. The approved version of that set is used; when you approve a
revision, the forecast moves onto it.

The forecast is marked **out of date** when entries are posted after it was made, when a new month
has closed, or when another version of the assumptions is approved. When it is re-run depends on
the change:
- a **material change** (a newly approved version of the assumptions, a closed month, a new
  horizon, or postings since the last run whose debits add up to at least the **materiality**
  you set) re-runs it within 15 minutes;
- other postings re-run it at the **regular interval** you choose (every hour by default; from
  15 minutes to once a day);
- **Refresh now** re-runs it at once.

Earlier forecasts are kept and never change. A rolling forecast is never published by itself: the
**published** projection stays the reference for the outlook and goals until you publish a newer
one. Months beyond the assumption set repeat the set's value for the same month of the year.

Its runs appear in the projections list marked **rolling forecast**; its state (up to date, or
out of date and why) is shown with a **Refresh now** button.

**Accuracy** compares, for each of the last 12 closed months, what the forecasts made one, three
and six months earlier expected with what happened: revenue, EBITDA and cash at the month end.

## Full-year outlook
The outlook (**Cash & planning → Full-year outlook**) shows a whole fiscal year: the
months up to the latest published projection's cut-over come from your posted books and are marked
**actual**; the later months come from that projection and are marked **forecast**. A divider
separates the two. Quarters and the year are sums of their months (cash: the month-end figure);
a quarter or year that spans the divider is marked **actual + forecast**. Without a published
projection for the year, the outlook shows the actual months only and says so.

Goals use the published projection as their likely outcome for the months it covers, and say so.

## Tax rules
Corporate tax rules are kept per country as dated rule sets: the rate, how long losses can be
carried forward, when provisional tax is paid and when the final balance is due, each with the
publications it was taken from. Cyprus is the first country: 12.5% for tax years 2020–2025 and
15% from 2026; losses carried forward 5 years (7 years for losses from 2026); provisional tax in
two halves by 31 July and 31 December; the balance by 1 August of the following year.

You **checked these rules on 27/11/2026** (brief 27). That is shown wherever they are used, and it
is not a verification by a Cyprus tax professional. They are not tax advice, and the platform never files a tax return.
See them with `GET .../tax-rules`.

Projections use these rule sets (see *Corporate tax*); a projection whose years no rule set
covers cannot be run. Each run records the rule set of each year and whether it was verified.
