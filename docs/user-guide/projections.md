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
With an approved set, open **Cash & planning → Projections**, choose the set and select **Run**. It starts
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

### Reading a projection
- **Natures.** Every column says **Actual** (the opening balance sheet, from your books) or
  **Forecast**, in words as well as by its border style. Show it by month, quarter or year.
- **Checks.** The six checks are listed with **holds** or **fails**; a failed check names the month
  where it failed, and such a projection cannot be published.
- **Explain a line.** Select any figure to see where it comes from: the assumption and how it is
  used, the fixed-asset register, your books, or which other lines it is worked out from.
- **Chart.** Cash at the end of each period; the balance-sheet table holds the same figures.
- **Publish.** A valid projection can be published (with planning publish permission). The
  outlook and goals use the latest published projection.
- **Export to Excel.** One sheet per statement, with a row stating the nature of each column and a
  note that the figures are a projection, not actual results.

## Rolling forecast
A rolling forecast looks at the next 12 or 24 months from the end of the last full month, and
moves on by itself. Set it up once at the bottom of **Cash & planning → Projections**: choose an
assumption set and the horizon. The approved version of that set is used; when you approve a
revision, the forecast moves onto it.

The forecast is marked **out of date** when entries are posted after it was made, when a new month
has closed, or when another version of the assumptions is approved. It is then re-run within the
hour (or at once with **Refresh now**); earlier forecasts are kept. Months beyond the assumption set
repeat the set's value for the same month of the year.

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

These rules are **pending verification** by a Cyprus tax professional and are shown as such
wherever they are used. They are not tax advice, and the platform never files a tax return.
See them with `GET .../tax-rules`.

The tax rate is the one from your books or the one you enter; the platform does not assume a rate
from tax law.
