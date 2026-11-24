# 2. Scenarios and figures worked out by hand

Six synthetic companies, each over the 24 months January 2027 to December 2028 from a cut-over at
31 December 2026. Inputs: `scenarios/<name>.json`. Every figure below was worked out by hand from
the inputs and the conventions (`01-scope-and-method.md` §1.2), then compared with the
independent model and the engine (both agree with each figure). Months are written 2027-01.
All tax rules here are scenario inputs for testing (pending the Cyprus verification, #154).

## S1 Base: the 24-month golden model
Sales 20,000 and other revenue 500 a month; margin 45%; payroll 4,000 and rent 1,200; new
equipment 12,000 in 2027-06 over 48 months; other debt 12,000 at 6%, 250 repaid a month; a
dividend of 20,000 in 2028-06; registered assets depreciating 400 a month for 15 months; tax at
12.5% (the test rule set of the engine's golden test), instalments half on 31 July and 31
December, the balance on 1 August of the next year; 3,000 of 2026 tax owed at the cut-over.

| Figure | By hand | Result |
|---|---|---|
| Revenue, every month | 20,000 + 500 | 20,500.00 |
| Cost of sales | 20,000 x 55% | 11,000.00 |
| EBITDA | 20,500 - 11,000 - 5,200 | 4,300.00 |
| Depreciation of the new equipment | 12,000 / 48, from 2027-07 | 250.00 |
| Interest in month n (0 = 2027-01) | (12,000 - 250 n) x 0.5% | 2027-01: 60.00; 2028-12: 31.25 |
| Interest over 24 months | 0.5% x (24 x 12,000 - 250 x (0 + ... + 23)) = 0.5% x 219,000 | 1,095.00 |
| Taxable profit 2027 | 12 x 4,300 - 0.5% x (144,000 - 250 x 66) | 50,962.50 |
| Tax 2027 / 2028 | 12.5% x 50,962.50 = 6,370.3125; 12.5% x 51,142.50 | 6,370.31 / 6,392.81 |
| July 2027 instalment | tax to date 3,713.28 x 12/7 x 1/2 | 3,182.81 |
| December 2027 instalment | 6,370.31 - 3,182.81 | 3,187.50 |
| 2026 balance paid 2027-08 | opening balance | 3,000.00 |
| Receivables at 2028-12 | 20,500 x 30 / 31 | 19,838.71 |
| Payables at 2028-12 | 11,000 x 30 / 31 | 10,645.16 |
| Accumulated depreciation at 2028-12 | 6,000 + 15 x 400 + 18 x 250 | 16,500.00 |
| Retained earnings at 2028-12 | 36,000 + net income 78,841.88 - 20,000 | 94,841.88 |

## S2 Losses carried forward
Payroll 16,000 a month in 2027 (a loss), 4,000 in 2028; losses brought forward: 3,000 from 2020
and 8,000 from 2024; 1,500 of non-deductible costs in 2028-03; 12.5% and 5 years to 2025, 15% and
7 years from 2026.

| Figure | By hand | Result |
|---|---|---|
| Profit before tax 2027 | 12 x (9,000 - 17,200 - 400) | -103,200.00 |
| Tax loss 2027 | -103,200 + depreciation 4,800 (added back; no allowances) | 98,400.00 arising |
| 2020 loss | usable 2021-2025 (5 years); unused | 3,000.00 expired at 2027-12 |
| Taxable profit 2028 | 40,800 + 4,800 + 1,500 | 47,100.00 |
| Losses used in 2028 | oldest first: 8,000 (2024) + 39,100 (2027) | 47,100.00; tax 0 |
| Losses carried forward at 2028-12 | 98,400 - 39,100 | 59,300.00 |
| Tax payments | no tax in either year | none |
| Cash | negative from 2027-08 (no credit facility): stated by the projection each month | lowest -39,109.68 at 2027-12 |

## S3 Negative cash and the credit facility
Opening cash 3,000; equipment of 45,000 in 2027-03; a facility with a limit of 20,000 at 9% keeps
cash at 1,000 where it can.

| Figure | By hand | Result |
|---|---|---|
| Facility in 2027-01 and 2027-02 | drawn each month to bring cash to the 1,000 minimum | 4,637.75 drawn by 2027-02 (557.10 of it in 2027-02) |
| 2027-03 | the facility is drawn to its limit; cash still below zero | drawn 15,362.25; cash -27,146.03 |
| Facility interest 2027-03 | 4,637.75 x 9% / 12 | 34.78 |
| Facility interest from 2027-04 | 20,000 x 9% / 12 | 150.00 |
| Tax per month from 2027-04 | (EBITDA 500 - interest 150) x 15% (depreciation not deductible: no allowance rate) | 52.50, although profit before tax is -500 |
| Closing cash 2028-12 | facility still at its limit | -21,113.72 |

## S4 Loans: variable rate, early repayment, new borrowing
TERM-1 (annuity, 50,000, 5%, 60 months; 6.5% from 2027-07; 10,000 repaid early in 2027-12);
BULLET-1 (20,000, 4%, 18 months); NEW-1 (equal principal, 30,000 drawn at the end of 2027-03, 7%,
36 months of which 3 interest-only; 5,000 more drawn in 2028-02); other debt 6,000 at 8%, 4,000
borrowed in 2027-05 and 500 repaid a month.

| Figure | By hand | Result |
|---|---|---|
| TERM-1 interest 2027-01 | 50,000 x 5% / 12 | 208.33 |
| TERM-1 payment and principal 2027-01 | annuity 50,000 over 60 at 5%/12 = 943.56; - 208.33 | 735.23 |
| BULLET-1 interest | 20,000 x 4% / 12 | 66.67 a month; repaid in full in 2028-06 |
| Interest 2027-01 | 208.33 + 66.67 + 6,000 x 8% / 12 | 315.00 |
| NEW-1 interest-only months 2027-04 to 2027-06 | 30,000 x 7% / 12 | 175.00 |
| NEW-1 principal from 2027-07 | 30,000 / 33 months left | 909.09 |
| TERM-1 after the early repayment, interest 2028-01 | 31,113.01 x 6.5% / 12 | 168.53 |
| Other debt | 6,000 + 4,000 = 10,000 at 500 a month, repaid by 2028-08; later repayments capped at 0 (stated) | |

## S5 Changing revenues and working capital
Seasonal sales (30,000 x a monthly factor; +8% in 2028; -10% from 2028-07); services 3,500 a month
from 2027-04; margin 42% in 2027, 38% in 2028; DSO 35 then 50 days; DIO 40 then 55; DPO 30 then
25.

| Figure | By hand | Result |
|---|---|---|
| Sales 2027-01 | 30,000 x 0.80 | 24,000.00 |
| Cost of sales 2027-01 | 24,000 x 58% | 13,920.00 |
| Receivables 2027-01 | 24,000 x 35 / 31 | 27,096.77 |
| Inventory 2027-01 | 13,920 x 40 / 31 | 17,961.29 |
| Payables 2027-01 | 13,920 x 30 / 31 | 13,470.97 |
| Interest 2027-01 | 20,000 x 5.5% / 12 | 91.67 |
| Revenue 2027 / 2028 | sums of the months | 391,500.00 / 410,712.00 |

## S6 Unexpected expenses, capital allowances and deferred tax
A one-off cost of 60,000 in 2027-09; professional fees of 8,000 in 2027-10, 5,000 of them not
deductible; equipment of 36,000 in 2027-02 (60 months; a synthetic 20% capital allowance, full
year in the year of spend); 15,000 of shares issued in 2027-10; a dividend of 10,000 in 2028-12.

| Figure | By hand | Result |
|---|---|---|
| Profit before tax 2027-01 | 24,300 - 12,480 - 7,000 - 500 - 10,000 x 6% / 12 | 4,270.00 |
| Allowance 2027 | 36,000 x 20% | 7,200.00 (600 a month) |
| Taxable profit 2027-01 | 4,270 + 500 - 600 | 4,170.00; tax 625.50 |
| Deferred tax 2027-01 and 2027-02 | (600 - 0 depreciation of the equipment) x 15% | 90.00 each; 180.00 at 2027-02 |
| Deferred tax from 2027-03 | allowance 600 = depreciation 36,000 / 60 | unchanged at 180.00 |
| 2027-09 | the one-off cost turns the year to date into a loss: tax accrued so far is reversed | current tax -5,010.30 |
| Tax 2027 | the year is a tax loss | 0.00; loss of 12,861.00 carried forward |
| July 2027 instalment, refunded | paid on the year to date before the loss; refunded on the final date | 3,757.05 paid 2027-07; refunded 2028-08 |
| Tax 2028 | (50,355 - 12,861) x 15% | 5,624.10 |
