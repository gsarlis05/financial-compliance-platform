# Fixed assets

Open **Bookkeeping → Fixed assets**.

## Add an asset
Select **Add a fixed asset** and enter its code, name, category, the date you bought it, its cost,
the value it will have at the end of its life (residual value, often 0) and its useful life in
months. Choose the method:
- **Straight-line:** the same amount every month;
- **Declining balance:** a percentage of the remaining book value each year (for example 40%),
  spread over the months.

The usual accounts are suggested: 1010 for the cost, 1019 for accumulated depreciation and 6600 for
the depreciation expense. You can choose others.

Depreciation begins when the asset is **available for use** (IAS 16), which is the purchase date
unless you enter another. Choose how it starts:
- **From the available-for-use date (pro rata by days)**, the default: the first month counts only
  the days the asset was in use, and the schedule runs one month longer so the full life is used;
- **From the next month**: the first full month after the asset became available;
- **Full month**: a full month from the month it became available.

Each month is rounded to cents, and the last month takes any remainder, so the total is exactly
the cost less the residual value. Select **Schedule** to see every month; the convention is
written above it.

You can correct an asset until its depreciation is first prepared. After that its terms are locked;
if they were wrong, record a disposal and add it again.

## Prepare the monthly depreciation
Under **Monthly depreciation**, choose the month and select **Prepare the draft entry**. You get one
draft journal entry with a line pair for every asset. It goes through the normal submission,
approval and posting, like any other entry. Each month is prepared once; if you void or reject the
draft, you can prepare that month again.

## Dispose of an asset
Select **Dispose**, enter the date and what you received for it. Depreciation stops from that
month, and the register shows the gain or loss. Book the disposal itself as a journal entry.

## Tax capital allowances
Capital allowances (tax depreciation) are kept **separately** from accounting depreciation: they
never change the schedule, the book value or any entry.

1. Under **Capital allowance classes**, add each class you need with its annual rate, the
   first-year rule (full allowance, months in use, or none) and the tax year it applies from.
   Say where the rate comes from (the law and article, or your tax adviser). No rates are built
   in. To change a rate, add it again from a later tax year; earlier rates are kept.
2. Give an asset its class when you add it. You can also set or change it later, even after
   depreciation has been prepared.

The schedule then shows the allowance for each tax year and the tax written-down value.
Allowances stop in the year of disposal; balancing allowances or charges on disposal are not
worked out. Projections use these allowances to work out taxable profit.
