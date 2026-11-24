# 3. Discrepancy report

## 3.1 Engine against the independent model
**No differences.** All six scenarios: 8,928 statement values (1,488 per scenario: 62 lines x 24
months), 432 loan figures and 21 tax payments compared; every value is identical to the cent
(none needs the EUR 0.01 tolerance). The model's reconciliation checks (1,308) and the engine's
eight invariants all hold in every month; the workbook's live reconciliation formulas, recalculated
by LibreOffice, are 0 in every month. Details: `results/summary.md`; line by line:
`results/<scenario>/comparison.csv`.

## 3.2 Issues found and corrected while preparing the package (M6F-1 to M6F-8)
Each was found by building the independent figures or the live checks, and was corrected in the
pull request named, with a test.

| # | Where | Issue | Cause | Correction |
|---|---|---|---|---|
| D1 | Engine (M6-3) | The tax payable line held VAT and income tax together; at the start of each fiscal year the whole balance, VAT included, was paid out as tax | One balance-sheet line for all taxes | Income tax payable and deferred tax are separate lines; VAT and other taxes are held (M6F-5, #159). Demo: closing cash 2028 corrected by +97,237.96 |
| D2 | Engine (M6-3) | Tax as a flat effective rate from the books on positive profit only; losses lost; no instalments | Simplified M6-3 model | The tax book of ADR-0046 (M6F-5, #159) |
| D3 | Tax book | Tax losses carried fractions of a cent between years | The year's taxable profit was not rounded before entering the loss pool | Rounded to cents at the year end (rule R1) (M6F-5) |
| D4 | Tax book | Recognising a deferred tax asset on losses brought forward could create a deferred tax **liability** when the books held no asset | The asset was assumed to be in the books | The books' asset counts first; any rest is credited in the first projected month (IAS 12) (M6F-5) |
| D5 | Goals (M6-5) | With a published projection, a goal's "against budget" analysis compared with the projection's remaining months, not with the budget | One plan slot for both the forward reference and the benchmark | The approved budget is pinned separately (M6F-7, #161) |
| D6 | Demo (M6F-3) | With IAS 16 pro-rata commencement, a December depreciation charge was never posted | Demo assets bought in December, available at once | Brought into use on 1 January (M6F-3, #157) |
| D7 | Scenario S4 (this package) | The opening balance sheet did not balance (by 10,000) | Input error in the scenario | Corrected; the model now refuses an unbalanced opening balance sheet |

## 3.3 Observations for the reviewer (not differences; judgements to confirm)
| # | Observation | Where | Question for the reviewer |
|---|---|---|---|
| O1 | Without a capital allowance rate, accounting depreciation is added back and nothing is deducted, so taxable profit exceeds accounting profit, and tax is charged in months with an accounting loss | S3 | Appropriate default until allowance classes are set up (#154), or should the projection warn when capex has no allowance class? |
| O2 | Current tax is accrued year to date; a later loss in the year reverses earlier tax in the month it occurs (negative current tax that month) | S6 2027-09 | Acceptable presentation for monthly management projections (the year total is right)? |
| O3 | Provisional instalments are estimated on the year to date, annualised; when the year turns out lower, the excess is refunded on the final date | S6 | Is a refund on the final date the right assumption, or should overpaid provisional tax be offset against the next year? |
| O4 | VAT and other taxes payable are held at their cut-over balance (steady state) | all | Acceptable for 24-month projections? |
| O5 | A loan's current portion is its scheduled principal of the next 12 months; early repayments are not anticipated | S4 | Consistent with IAS 1.69 as applied by the entity? |
| O6 | Negative cash is shown, with a note each month, when the credit facility is exhausted; no automatic financing is assumed | S2, S3, S6 | Agreed? |
| O7 | S1 uses the engine's test rule set (12.5% in all years), kept identical to the earlier golden model; S2 to S6 use the Cyprus-like rates (12.5% to 2025, 15% from 2026) | S1 | None; noted for clarity |

## 3.4 Unresolved
None of the comparisons is unresolved. What remains open is the professional review itself
(`04-acceptance-checklist.md`) and the verification of the Cyprus tax rules (#154).
