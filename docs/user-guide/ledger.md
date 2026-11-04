# User guide: workspaces and the general ledger (Milestone 1)

This guide covers what you can do in the web app today. The interface is in English and Greek
(switch with the **Language** menu at the top right). Amounts are always shown with two decimals.
A missing or broken feature is a bug, so please report it with the correlation ID shown in the
error message.

> Milestone 1 runs on local development machines only, with **synthetic data**. Do not enter real
> client or business data until a production environment is approved (ADR-0010).

## 1. Signing in
Select **Sign in**. You are sent to the identity provider, which asks for your password and a
one-time code from your authenticator app. Two-factor sign-in is mandatory: you set up the
authenticator on your first sign-in. Sessions end after 30 minutes without activity and always
after 12 hours.

Some sensitive actions (approving a period unlock) need a sign-in from the last 5 minutes. If yours
is older, you are asked to sign in again; nothing you entered is lost.

## 2. Workspaces and legal entities
A **workspace** holds the books of one customer. Each has a kind, shown by the colour of the
switcher:

| Kind | Use | Legal entities | Approval of entries |
|---|---|---|---|
| Business | a company and its subsidiaries | one or more | always (default) |
| Personal | your household finances | exactly one (created for you) | none: you post directly |
| Firm | an accounting firm's own practice | one or more | always |

Create one on the **Your workspaces** page. A business workspace asks for its first legal entity.

Inside a workspace, the menu bar groups the pages:

| Menu | Pages |
|---|---|
| Bookkeeping | Journal entries, Approvals |
| Customers & suppliers | Customers & suppliers, Receivables & payables |
| Reports | Trial balance, Statements |
| Setup | Chart of accounts, Dimensions, Statement mapping, Periods |
| Controls | Integrity |

Select a menu to show its pages. With the keyboard, use Tab to reach a menu, then Enter or the
down arrow to open it. The arrow keys move between pages, and Escape closes the menu.
Data never crosses workspaces: the database itself refuses it, not just the screens.

## 3. People and roles
The owner invites people by email with a role. An invitation link is valid for 7 days and works
once. You cannot grant a role with permissions you do not hold yourself.

| Role | Can |
|---|---|
| Owner | everything, including locking periods and approving unlocks |
| Finance manager, Partner | prepare, approve, post, lock periods, approve unlocks, settings |
| Accountant | maintain accounts and periods, prepare and submit entries, request unlocks |
| Reviewer | approve and post entries |
| Client user, Read only | view books and reports |
| Household member (personal) | prepare and post entries |

**Segregation of duties:** the person who prepared an entry cannot approve it, and a period unlock
needs two approvers other than the requester.

## 4. Chart of accounts
On **Chart of accounts**, an empty entity offers two templates:
- **Cyprus business**: 55 accounts with English and Greek names (assets 1xxx, liabilities 2xxx,
  equity 3xxx, income 4xxx, cost of sales 5xxx, expenses 6xxx–7xxx, suspense 9999);
- **Personal finances**: 29 accounts for a household.

Headings (shown with "· heading") group accounts and cannot be posted to. Add your own accounts
below the table. Accounts are never deleted (postings must keep their account); deactivating
an account is available through the API in M1.

## 5. Fiscal years and periods
On **Periods**, create a fiscal year from its first day. It gets 12 monthly periods plus an
adjustment period for year-end entries. Each period is:

| Status | Meaning | Who changes it |
|---|---|---|
| Open | entries can be posted | — |
| Soft-closed | only finance managers/owners can post | accountant (and back to open) |
| Locked | nothing can be posted | finance manager or owner; reopening needs an unlock |

### Year-end close
At the bottom of each fiscal year on **Periods**, open **Year-end close**.
- The panel shows the result still to close and anything that blocks the close: an earlier year
  that is still open, entries dated in the year that are not posted, or a closing entry already
  waiting.
- Choose the retained-earnings account (3200 by default) and select **Generate closing entry**. The
  system creates an entry that brings every income and expense account to zero (per dimension
  value too) and puts the result in retained earnings. It is submitted for approval like any other
  entry, and nobody can edit it.
- Posting it **closes the year**: nothing more can be posted into it. If balances changed after the
  closing entry was generated, posting is refused; void it and generate it again.
- A closed year shows its checks: income and expense accounts are zero at the year-end, and next
  year's opening balances equal the closing balance sheet. Balances carry forward automatically;
  no opening entry is needed.
- To change a closed year (for example an audit adjustment), choose **Re-open the year** with a
  reason. This creates a reversal of the closing entry for approval. Once it is posted, the year is
  open again; post the adjustment and close again. Closing and re-opening need the *lock periods*
  permission (owners and finance managers).

The profit and loss statement of a closed year still shows its result; the balance sheet shows it in
retained earnings.

## 6. Journal entries
**New entry** opens the entry form. Choose the date, a description and at least two lines. The
totals update as you type. **Save and submit** stays disabled until debits equal credits and every
amount is valid (use a dot for decimals: `120.50`). The form warns you when the date falls in a
soft-closed or locked period.

Lifecycle: **Draft → Submitted → Approved → Posted**. Drafts can be edited or voided. A reviewer can
approve or reject (with a reason) a submitted entry; rejected entries go back to the preparer.
Posting gives the entry its permanent number (for example GJ-42) without gaps.

**Posted entries can never be edited or deleted.** To correct one, open it and choose **Reverse**
with a reason. The reversal is a new entry that follows the same approval workflow. Then post the
correct entry. An entry can be reversed only once.

**Bookkeeping → Approvals** lists entries waiting for you.

## 7. Period unlocks (exceptional)
To correct a locked period, an accountant requests an unlock with a reason and a time window
(5 minutes to 8 hours). Two different approvers (not the requester) approve it, each having
signed in within the last 5 minutes. While the unlock is active, entries can be posted to the period
and are tagged with the unlock. The period locks again when the window ends or the unlock is closed.
See the [period unlock runbook](../runbooks/period-unlock.md).

## 8. Reports
- **Trial balance** as of a date (or for a date range), with a CSV export. Debit and credit totals
  must always match; the page says so if unposted entries exist in the range.
- **General ledger** per account with opening balance, lines and closing balance (API and CSV in
  M1; a screen comes later).

CSV exports neutralise cells that spreadsheet programs would run as formulas.

## 9. Customers, suppliers and open invoices
**Customers & suppliers** holds the register: code, name, kind, VAT number, email and payment terms
(names, VAT numbers and emails are personal data; they are masked in the audit trail).

The Cyprus template marks **1200 Trade receivables** and **2100 Trade payables** as control
accounts. Every line on a control account needs a customer or supplier (the entry form shows a
picker and an invoice-number field on those lines). Those posted lines *are* the open items: an
invoice on receivables is a debit, a payment or credit note a credit; payables the other way round.
The due date is the line's due date, or the document date plus the payment terms.

**Receivables & payables** shows, at any date, what is open per customer or supplier in the
buckets *not yet due*, *1–30*, *31–60*, *61–90* and *over 90 days*, plus unmatched payments. The
total always equals the control account in the trial balance; the page says so, and warns if not.
Open a customer to see its items and **Match payments automatically** (same invoice number first,
then the oldest invoices). Matches can also be made or removed one by one through the API, and an
invoice can be flagged as disputed (automatic matching skips it). A reversed invoice becomes a credit
note that cancels it. CSV export is available.

## 10. VAT codes
Each line can carry a **VAT code** from the Cyprus catalogue: S19 (standard 19%), R9 and R5
(reduced), Z0 (zero), EX (exempt), RC (EU reverse charge), OUT (outside the scope) and SETTLE
(payments to or refunds from the tax authority). Lines on the VAT accounts (**1220** input VAT,
**2120** output VAT) must have one, and the code must be valid on the accounting date.

> **All rates are marked "unverified"** until a Cyprus tax professional confirms them (decision
> #93). The 3% rate is not in the catalogue yet for the same reason. The app does **not** produce or
> submit VAT returns; that comes with the rules engine (M9), with human sign-off.

The catalogue is reference data maintained by the platform (versioned by validity dates); the app
itself can only read it.

## 11. Statement mapping
Every postable account feeds one **line of the financial statements** (for example *1300 Bank*
→ *Cash and cash equivalents*; *6100 Rent* → *Rent*). The same structure will drive KPIs, budgets
and projections, so each figure is defined once. The structure (taxonomy *IFRS_SME_CY 1.0*) is
reference data maintained by the platform.

On **Statement mapping**, *Apply default mapping* maps the whole Cyprus business chart in one go
(existing choices are kept). Each account can only be mapped to a line that fits its type: assets,
liabilities and equity to the balance sheet, income and expenses to the profit and loss.

At any date, the page says whether the mapping is **complete**. An account with a balance but no
mapping blocks the statements (section 12) until it is mapped; *9999 Suspense* is deliberately unmapped, so
statements stay blocked while it holds a balance. Every change keeps the previous version (history
per account) and is recorded in the audit trail.

## 12. Financial statements
**Statements** shows the *profit and loss*, *balance sheet* and *cash flow statement* for the
period you choose (the balance sheet is at the end date). It also shows the same period one year
earlier unless you untick *Compare with the prior year*. These are **management statements**
built from the statement mapping, not statutory financial statements.

- Income is shown positive and expenses negative. Subtotals run from gross profit to the profit for
  the period.
- Until the year is closed, equity shows the *profit (loss) for the year to date* (and any result
  of earlier years not yet closed) as separate rows.
- The cash flow statement starts from profit, adds back depreciation, adjusts for changes in
  working capital, and then shows investing and financing. It ends at the cash balance.
- Select a line to see its accounts, and an account to see its ledger lines; each entry number
  opens the entry.
- Every time, the system checks four things:
  - the balance sheet balances;
  - the result equals the movement in equity (apart from capital paid in or distributed);
  - the cash flow equals the movement in cash;
  - equity agrees with the accounts.

  If a check ever fails, the page says so; please report it.
- If an account with a balance is not mapped, the statements are blocked and the page lists the
  accounts, with a link to **Statement mapping**.
- **Export** as PDF (one page per statement), XLSX (one sheet each) or CSV, in the language you
  are using. Exports need the export permission and are recorded in the audit trail.

## 13. Integrity checks
On a schedule (`make ops-checks` locally; nightly once hosted) and on demand on **Controls → Integrity**
(owners, finance managers, partners and workspace admins), the system
checks that every posted entry balances, that stored balances equal the entry lines, that numbering
has no gaps, that locked periods were not changed, and that the audit trail's hash chain is intact.
A failure is an incident: see the [integrity runbook](../runbooks/integrity-check-failure.md).

## 14. Try it with demo data
`make demo SHARE_WITH=<your email>` creates a **Demo Trading** workspace with a year of synthetic,
monthly-summarised books and gives you access as finance manager. See [the demo script](../demo.md).
