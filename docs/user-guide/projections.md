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
     stock days (DIO), the days you take to pay suppliers (DPO), the tax rate and the interest
     rate are taken from your books. Where the books cannot tell, the value is 0.
   - **The approved budget:** revenue, costs and margin from the budget for the months it
     covers; the last 12 months for the others.
   - **Empty.**
2. **Change what you expect to be different.** Each row is a driver, each column a month. Hover
   over a value to see where it came from; values you entered are shown in bold. **Fill right**
   copies a row's first month to all months. Select **Save changes**.
3. **Approve.** An approved set never changes. To change it, select **Revise as a new version**:
   you get a draft copy, and when you approve it the earlier version is marked superseded.

## Running a projection
With an approved set, run a projection (`POST .../projections`, screens follow in M6-6). It starts
from your actual balance sheet at the cut-over, read from the posted books, and works out each
month in a fixed order: income statement, interest on the debt at the start of the month, tax,
receivables, stock and payables from the days, fixed assets, debt, equity, the cash flow
statement, then the credit facility to keep the minimum cash.

Every run checks that the three statements agree: the balance sheet balances, the cash on it equals
the cash flow statement, retained earnings move only by profit and dividends, each month starts
where the last ended, and quarters and years add up. A run that fails a check is marked
**invalid**, says which check failed in which month, and cannot be published. Lines the
assumptions do not cover (intangibles, investments, other receivables and payables) stay at their
opening balance. If an account with a balance is not mapped to a statement line, map it first.

## Rolling forecast
A rolling forecast looks at the next 12 or 24 months from the end of the last full month, and
moves on by itself. Set it up once (`PUT .../rolling-forecast`, screens follow in M6-6): choose an
assumption set and the horizon. The approved version of that set is used; when you approve a
revision, the forecast moves onto it.

The forecast is marked **out of date** when entries are posted after it was made, when a new month
has closed, or when another version of the assumptions is approved. It is then re-run within the
hour (or at once with **Refresh**); earlier forecasts are kept. Months beyond the assumption set
repeat the set's value for the same month of the year.

**Accuracy** compares, for each of the last 12 closed months, what the forecasts made one, three
and six months earlier expected with what happened: revenue, EBITDA and cash at the month end.

The tax rate is the one from your books or the one you enter; the platform does not assume a rate
from tax law.
