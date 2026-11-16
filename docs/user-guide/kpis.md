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

## Your own KPIs
**Cash & planning → Custom KPIs** lets you write KPIs in the same formula language as the
library.

**Available in formulas:**
- `flow("REVENUE")`, `prior_flow(...)`;
- `balance("BS.AR")`, `opening(...)`, `avg_balance(...)`;
- `days()`, `annual_factor()`, `burn_3m()`;
- `count_metric("HEADCOUNT")` and `amount_metric("MRR")` for operational metrics;
- `+ - * /` and parentheses.

A key is a taxonomy section (`REVENUE`), line (`BS.AR`) or prefix (`BS.DEBT`).

**Check the formula** before saving. The check covers:
- the syntax;
- the unit against how the KPI is shown (a percentage needs a ratio, days need days);
- every taxonomy key and metric the formula names;
- a dry run on the last complete month.

Nothing is saved until the check passes.

**Personal and workspace KPIs:**
- **Personal** KPIs are only for you and are in use at once. They appear under **Your personal
  KPIs** on the KPIs page, computed on the same figures as the calculated set, and are not stored
  with it, so no one else sees them.
- **Workspace** KPIs are shared. They are proposed by a preparer and must be approved by someone
  else (finance manager, partner or owner). Once approved, they are part of every new KPI
  calculation, in a *Custom* group.

**Versions:**
- A change is a new version.
- A personal version replaces the old one at once.
- A workspace version waits for approval, and the approved version stays in use until then.
- Every value names the version it was computed with, so earlier calculations keep their meaning.

## Operational metrics
Operational metrics are figures that are not in the books, such as customers, headcount, units
sold or MRR. You enter them by hand each month.

**Setting one up:**
- Choose *value at the end*, such as headcount, where the period's last month counts.
- Or choose *total of the months*, such as units sold.

**What to know:**
- A correction keeps the earlier value with who entered it.
- A calculation keeps the values it used, so a later correction does not change it.
- Every KPI that uses an operational metric is marked **Includes data not from the ledger**.
- A total metric with a month missing is shown as not meaningful.

## Library version 1.1 (new KPI sets)
New KPI sets use library **CORE@1.1**: the KPIs above, unchanged, plus four more.

| KPI | How it is worked out | Not meaningful when |
|---|---|---|
| Net debt / EBITDA | (borrowings − cash) at the end of the period over EBITDA of the 12 months to the end of the period. Negative means more cash than debt. | EBITDA of those 12 months is zero or negative |
| Debt service coverage (DSCR) | (EBITDA − income tax of the 12 months) over the year's interest plus the debt due within 12 months of the period end | there is no interest and no debt due within 12 months |
| Receivables turnover | revenue of the period, per year, over average receivables | average receivables are zero |
| Inventory turnover | cost of sales of the period, per year, over average stock | average stock is zero |

Earlier KPI sets keep the definitions they were calculated with (CORE@1.0).

## KPIs on projected and scenario figures
For any year of an approved assumption set, or of a shared scenario next to its base, the same KPIs
are worked out on the projected figures (labelled forecast, or hypothetical for a scenario). A KPI
that needs months the projection does not cover (for example growth against the year before the
cut-over) shows why instead of a number.

