# Milestone 1 demo script (AC-G5)

The demo loads **Demo Trading Ltd (Demo)**, a fictional Cypriot trading company, with one year (2026) of
synthetic books, and walks through the whole M1 workflow:

> invite users → create the chart of accounts → draft → approve → post → reverse → lock periods →
> trial balance → integrity check

## Run it
```sh
make dev                 # services, dependencies, migrations (once)
make demo                # or: make demo SHARE_WITH=you@example.com
```
`SHARE_WITH` invites an existing user (anyone who has signed in to the web app once) as
**finance manager**, so you can open the workspace in the UI at the printed link.

Expected output (about 45 seconds; the slug and numbers depend on the seed, 42 by default):
```
✔ owner created workspace demo-trading-xxxxxx with entity Demo Trading Ltd (Demo)
✔ invited and joined: demo accountant (prepares) and demo reviewer (approves, posts)
✔ chart of accounts applied (55 accounts) and FY2026 created
✔ 65 customers and suppliers registered
✔ 95 entries drafted by the accountant, approved and posted by the reviewer
✔ entry GJ-96 reversed with a reason and re-posted
✔ periods 1-11 locked; posting into January is refused (409), rejected and voided
✔ trial balance at 2026-12-31: 1810572.51 = 1810572.51; bank 371514.38 matches the synthetic statement
✔ 442 payments matched to invoices; receivables 203631.60 and payables 102084.19 reconcile to the ledger
✔ 43 accounts mapped to the financial taxonomy; mapping complete for statements
✔ actuals read model up to posting 98 matches the ledger
✔ statements for 2026: balance sheet balances at 700545.98; profit 89973.47 = movement in equity; cash flow ends at the bank balance 371514.38
✔ integrity checks passed (balance, snapshots, gapless numbering, audit chain)
✔ shared with you@example.com as finance_manager
```
Any failed step stops the script with the API's response, so a run that completes is itself the
proof. The same walkthrough runs in CI as `tests/devtools/test_demo.py`.

## What it does, and why it is trustworthy
- **Through the real API.** Every step is an HTTP call to the same endpoints the web UI uses
  (in-process), so CSRF, permissions, segregation of duties, row-level security and the database
  guards all apply. Apart from creating the demo user records, nothing writes to the database
  directly.
- **Three people.** A demo owner creates the workspace and invites a demo *accountant* (prepares and
  submits) and a demo *reviewer* (approves and posts). Nobody approves their own entries. Demo users
  are local records that cannot sign in.
- **Books.** The synthetic generator (M0-6, seed 42) produces 513 sales invoices, 167 purchase
  invoices, 632 bank transactions and a loan schedule for 2026. The loader books them as monthly summary
  entries (sales, purchases, customer receipts, supplier payments, payroll, rent, operating
  expenses, loan instalments split into interest and principal, VAT payments), plus the opening
  share capital and the loan drawdown.
- **Customers and suppliers.** The 65 synthetic counterparties are registered, and receivables
  and payables lines are booked per customer and supplier. At year end, payments are matched to
  invoices automatically and the ageing of both sides must reconcile to the control accounts.
- **Cross-check.** The bank account (1300) in the trial balance must equal the synthetic bank
  statement's closing balance (less the 350.00 cleaning correction). Every euro is booked.
- **Correction.** A December cleaning bill is posted to *Utilities* by mistake, reversed with a
  reason (the reversal goes through approval too), and posted again to *Other operating expenses*.
- **Close.** January–November are soft-closed by the accountant and locked by the owner. An
  attempt to post a late January invoice is refused by the API (409, `ledger.period.locked`); the
  reviewer rejects it and the accountant voids it.

- **Statements.** The P&L, balance sheet and cash flow for 2026 are built from the read model and
  must pass their checks. The cash flow must end at the bank balance. The figures are pinned in
  `backend/tests/devtools/golden/demo_statements_2026.json` (AC-M2-8).

## Demo data simplifications
Monthly summaries instead of one entry per invoice (document-level posting arrives with
sub-ledgers); VAT payments are debited to output VAT without netting input VAT (VAT returns are M3);
the whole loan is shown as non-current. All names, VAT numbers and IBANs are fictional and marked
"(Demo)".

## Where "staging" fits
AC-G5 says *on staging*. No hosted environment exists in M1: production and staging deployments
need your approval (directive constraint), and the Terraform skeleton is validated but never
applied. The demo therefore runs on the local stack and in CI. It needs only the public API, so it
will run unchanged on staging once that is approved.
