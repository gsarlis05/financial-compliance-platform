# KPIs

**Cash & planning → KPIs** shows the core key performance indicators for a period of whole months.

## Calculate
Choose the month the period ends in and a period:
- month;
- quarter to date;
- year to date (from January);
- the last 12 months.

Then select **Calculate KPIs**. Each calculation is kept, and records the ledger posting it includes.
If entries are posted afterwards, the page says the KPIs are out of date: calculate again to include
them.

## The library (CORE 1.0)
| Category | KPIs |
|---|---|
| Profitability | Gross margin, operating margin, EBITDA margin, net margin, return on assets, return on equity |
| Liquidity | Current ratio, quick ratio, cash ratio, cash runway (months) |
| Efficiency | Days sales outstanding (DSO), days payables outstanding (DPO), days inventory outstanding (DIO), cash conversion cycle |
| Growth | Revenue, EBITDA and net profit growth against the same months a year earlier |
| Stability | Debt to equity, interest coverage |

The conventions:
- **Average balances** are the mean of the opening and closing balances.
- **Days** are the calendar days in the period.
- **Returns** are annualised (× 365 ÷ days).
- **DPO** uses cost of sales.
- **Equity** includes this year's result until the year is closed.
- **Cash runway** is cash divided by the average monthly decrease in cash over the last 3 months.

Every KPI shows its own convention and a worked example under **How is this computed?**.

## Not meaningful
When a KPI cannot be computed meaningfully, it shows **Not meaningful** and why, never 0 or ∞. For
example:
- "Revenue is zero";
- "Equity is zero or negative";
- "Not burning cash: it did not decrease over the last 3 months".

## Where a number comes from
**How is this computed?** shows:
- the formula;
- every account behind the value, and how it was used (movement in the period, opening or closing
  balance, a year earlier);
- the amount each account contributed.

**Entries** lists that account's journal entries in the period.

Accounts that have activity but no taxonomy line are not included, and the page says how many there
are. Map them under **Setup → Mapping**.

## Coming next
Your own KPIs and operational metrics such as headcount (M4-5).
