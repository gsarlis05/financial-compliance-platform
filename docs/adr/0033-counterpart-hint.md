# ADR-0033: The business ↔ personal counterpart hint is opt-in, confirm-only and stays in one workspace per request
Status: **Proposed** (M5-3; awaiting product owner review in PR) · Date: 2026-11-10

## Context
Doc 11 §4.2 says that payments between a business and its owner (salary, dividends, director loans,
drawings) are recorded in each set of books independently. An optional hint may **suggest** the
matching personal entry when a business payment to the owner is posted. The person must confirm
it in the personal workspace, and it is never posted automatically. The platform also keeps
**exactly one workspace per request** (`WorkspaceContext`, doc 11 §2) and allows no query across
workspaces.

## Decision
- **Opt-in link, stored in the personal workspace** (`personal_counterpart_link`): a business
  workspace, legal entity and account (for example 2020 Director loans), and the personal money
  account and income category the payments go to. It holds references only (no foreign key across
  workspaces). It can be revoked, not edited (trigger).
- **Suggestions are read in the business workspace, by the person, with their own permission
  there.** The personal page calls the business general ledger for the linked account
  (`reports.read`); each request enters one workspace. If the person loses access to the business,
  nothing is suggested. A suggestion is a debit on the linked account (money paid to the owner).
- **Confirm or dismiss, in the personal workspace** (`personal_counterpart_decision`, append-only
  by trigger and grants, one per business entry and link):
  - **Confirm** records a "received" transaction, which is a balanced entry posted with every
    ledger rule. The person can still undo it by reversal.
  - **Dismiss** records nothing.
- The business workspace never sees the personal workspace, the link or the decisions. Nothing
  is ever posted in the business books.

## Consequences
- No automatic data flow, and no new path across workspaces on the server. The person does on
  the page what they could do by hand in two browser tabs.
- The personal server cannot prove that a confirmed amount matches the business entry (it never
  reads the business). That is acceptable: it is the person's own entry in their own books, it
  is labelled with the business reference, and it can be undone.
- The read-only "summary share" from a business to the owner (doc 11 §4.3) remains a later,
  separate feature that the business grants.
