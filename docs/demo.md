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
✔ invoice cleaning-invoice.pdf attached to the cleaning entry (virus-scanned, type checked; the same file again is the same document); the EICAR test virus was refused
✔ periods 1-11 locked; posting into January is refused (409), rejected and voided
✔ trial balance at 2026-12-31: 1810572.51 = 1810572.51; bank 371514.38 matches the synthetic statement
✔ 442 payments matched to invoices; receivables 203631.60 and payables 102084.19 reconcile to the ledger
✔ bank statement imported (633 lines); importing it again created no duplicates; 17 matched to ledger entries automatically; reconciled at 2026-12-31: ledger 371514.38 = statement 371514.38
✔ 43 accounts mapped to the financial taxonomy; mapping complete for statements
✔ actuals read model up to posting 98 matches the ledger
✔ statements for 2026: balance sheet balances at 700545.98; profit 89973.47 = movement in equity; cash flow ends at the bank balance 371514.38
✔ year 2026 closed by the reviewed closing entry: profit 89973.47 moved to retained earnings; income and expense accounts are zero and the 2027 opening balances equal the closing balance sheet
✔ integrity checks passed (balance, snapshots, gapless numbering, closed years, audit chain)
✔ 13-week cash forecast from 2027-01-04: opening cash 371514.38, week 13 closing 420689.93; no shortfall below the minimum; run VALID and reproducible
✔ budget 2027 prepared by the accountant, approved by the owner: total 738000.00; sales 600000.00 phased like 2026 (Phased like the prior year's actuals.)
✔ 6 sample goals for 2027 set with frozen 2026 baselines and evaluated: Revenue 500k ON_TRACK; EBITDA margin 20% ON_TRACK; Cash at least 100k ON_TRACK; DSO 30 days OFF_TRACK; Net profit +15% ON_TRACK; Opex -10% ON_TRACK
✔ 1 in-app alert(s) raised by the evaluations: Goal DSO 30 days is off track
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
- **Documents.** A synthetic cleaning invoice (PDF) is attached to the corrected entry. Uploading
  it again returns the same document, and the EICAR antivirus test file is refused by ClamAV.
- **Close.** January–November are soft-closed by the accountant and locked by the owner. An
  attempt to post a late January invoice is refused by the API (409, `ledger.period.locked`); the
  reviewer rejects it and the accountant voids it.

- **Bank.** A CAMT.053 statement is built from the synthetic bank transactions (plus the December
  cleaning payment) and imported. Importing it again is refused, the lines that correspond to single
  ledger entries are matched automatically, and the bank reconciles to the ledger at year end. The
  monthly summary entries cannot be matched line by line; the balances still prove agreement.
- **Statements.** The P&L, balance sheet and cash flow for 2026 are built from the read model and
  must pass their checks. The cash flow must end at the bank balance. The figures are pinned in
  `backend/tests/devtools/golden/demo_statements_2026.json` (AC-M2-8).

- **Cash forecast.** The forecast includes:
  - synthetic commitments: rent, payroll, a utilities estimate, a 50,000 annuity loan, an
    overdraft, a VAT estimate and a manual grant;
  - the open receivables, dated at their due date plus each customer's observed days late;
  - the open payables.

  The forecast runs from 4 January 2027 with a minimum cash of 30,000. The run must be valid and
  must reproduce its output hash. The demo test also recomputes every week's closing from the
  run's stored inputs with an independent reference calculation. The figures are pinned in
  `backend/tests/devtools/golden/demo_cash_13w.json`, marked *not yet signed off* until a finance
  professional reviews them (AC-CW5).

- **Budget.** The accountant prepares *Budget 2027*: sales of 600,000 phased like the posted
  2026 sales, rent as quantity × rate (1 × 2,500 a month) and payroll of 108,000 spread evenly. The
  accountant submits it and the owner approves it, so segregation of duties holds.

- **Goals.** The owner sets the six sample goals for 2027 (revenue 500,000; EBITDA margin 20%;
  cash at least 100,000; DSO 30 days; net profit +15%; operating expenses −10%). Each baseline is
  computed from the 2026 actuals and frozen. Each goal is evaluated once: actuals to date, then the
  approved budget, or the cash forecast for cash. The reference figures for these goals are in
  `backend/tests/goals/test_goals.py`, *not yet signed off* by a finance professional (AC-GO2).
  The off-track goal raises an in-app alert (Cash & planning → Alerts, AC-GO4).

- **Year-end close.** The owner generates the closing entry for 2026, and the reviewer approves and
  posts it. The year is then closed, and the statements show the profit in retained earnings with
  the P&L unchanged.

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
