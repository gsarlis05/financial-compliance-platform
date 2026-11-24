# ADR-0046: Corporate tax in projections follows the versioned rules, separates expense, balances and payments
Status: **Proposed** (M6F-5, #150; awaiting product owner review in PR) · Date: 2026-11-16

## Context
Owner decision D4 (2026-11-15): Cyprus is the first jurisdiction, with 15% corporate income tax
from 2026; provisional payments, final balancing payments and their deadlines are modelled; tax
losses are carried forward (seven years for losses from 2026) rather than lost; income tax
expense, tax liabilities and cash tax payments are kept separate; rules and deadlines are
configurable, versioned and jurisdiction-specific. The M6-3 engine applied a single `tax_rate`
driver (taken from the books' effective rate) to positive profit, accrued it in one tax payable
line that also held VAT, and paid that whole line in the first month of each fiscal year.

## Decision
- **Rules come from the versioned rule sets (M6F-2)**, one per tax year, pinned in the run with
  their id and verification status (lineage `tax_rules:<id>`). A projection whose years no rule
  set covers is refused. The `tax_rate` driver is removed; a `tax_adjustment` driver (amount,
  either sign) carries non-deductible costs and non-taxable income. Tax years are calendar
  years (a rule set with another start month is refused for now).
- **Tax position of the set** (draft only, copied by a revision, audited): unused losses brought
  forward by the year they arose, provisional tax paid for the cut-over's tax year, and whether a
  deferred tax asset is recognised on losses (IAS 12.34 judgement, off by default).
- **Taxable profit** = profit before tax + accounting depreciation − capital allowances (the
  register's, M6F-3, and those of new capex at `capex_allowance_rate`, full first year) + tax
  adjustments. For the tax year of the cut-over the actual months come from the books.
- **Current tax** is accrued on a year-to-date basis: tax on (taxable profit to date − usable
  losses), never negative, at the year's rate; each month's expense is the change, so the year's
  total is the year's tax exactly (to the cent). At the year end losses are used oldest first,
  a new loss is added, and losses past the carry-forward of the year they arose expire.
- **Payments:** provisional instalments on the rule set's dates, each bringing the year's
  payments to the instalment's cumulative share of the year's tax as projected at that month
  (year to date, annualised), never negative (this avoids a circular dependence between tax,
  interest and the credit facility); the final balance (or refund) on the final date; the opening
  balance owed for earlier years on the previous year's final date, or in the first month if that
  date has passed.
- **Deferred tax (IAS 12)** at the year's rate on (capital allowances − depreciation of the same
  assets), cumulative from the cut-over, plus a deferred tax asset on usable losses only if
  recognised; the opening deferred tax is the books' balance. The books' deferred tax asset, up
  to the tax value of the losses brought forward, is taken to be the asset on those losses, so
  only its movement is projected; any rest is recognised (credited to profit) in the first
  projected month. The projection therefore never creates a liability out of an asset the
  books do not carry. With the asset recognised, a year's total tax expense is the rate times
  its accounting profit, before permanent differences.
- **Statements:** income statement current tax, deferred tax and income tax; balance sheet
  income tax payable (receivable if negative) and deferred tax, separate from VAT and other
  taxes payable, which are now held at their cut-over balance (accounts are told apart by
  their VAT role); cash flow: income tax expense added back and income tax paid, both in
  operating activities (IAS 7.35).
- **Eighth invariant, `tax_reconciles`:** each month the income tax balance moves by current tax
  less payments, the deferred tax balance by deferred tax, the income statement's tax equals
  current plus deferred, the cash flow's tax lines equal the expense and the payments, and at
  each year end the loss pool rolls forward (before + arising − used − expired = after). Engine
  version 3.

## Consequences
- The demo's 2028 net income is now after 15% tax (it booked no income tax before); its cash no
  longer pays out the VAT balance as if it were income tax.
- Version 1 and 2 runs stay stored as they were.
- **Limitations:** late-payment interest, penalties and the underestimation charge are not
  modelled; rolling forecasts starting in a later tax year use the set's provisional payments
  only for the cut-over year; new capex allowances use a full first year; balancing allowances on
  disposal are not modelled; tax years must be calendar years. The rules are pending
  verification by a Cyprus tax professional (#154), and the engine stays
  `PENDING_PROFESSIONAL_REVIEW` (M6F-8).
