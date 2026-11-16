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

Depreciation starts the month after you bought the asset. Each month is rounded to cents, and the
last month takes any remainder, so the total is exactly the cost less the residual value. Select
**Schedule** to see every month.

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
