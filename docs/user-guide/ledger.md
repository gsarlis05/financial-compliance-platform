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

The **Approvals** tab lists entries waiting for you.

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

## 9. Integrity checks
On a schedule (`make ops-checks` locally; nightly once hosted) and on demand on the **Integrity**
tab (owners, finance managers, partners and workspace admins), the system
checks that every posted entry balances, that stored balances equal the entry lines, that numbering
has no gaps, that locked periods were not changed, and that the audit trail's hash chain is intact.
A failure is an incident: see the [integrity runbook](../runbooks/integrity-check-failure.md).

## 10. Try it with demo data
`make demo SHARE_WITH=<your email>` creates a **Demo Trading** workspace with a year of synthetic,
monthly-summarised books and gives you access as finance manager. See [the demo script](../demo.md).
