# 18 — Milestone 5 Implementation Brief: personal MVP and pilot readiness

Status: **IN PROGRESS**. Product owner go-ahead 2026-11-10: "Later on the design will be changed
so continue with what is easier for now for best coding". Backlog:
[08 §M5](08-implementation-backlog.md). Specification: [11](11-account-types-and-coexistence.md)
(customer types and coexistence) and [10](10-cfo-fpa-specification.md) for the planning parts.

## 1. Business purpose
- **Your personal finances on the same platform.** A personal workspace has its own books, in plain
  words: accounts, spending and income by category, net worth, and a personal budget, goals and a
  12-month cash outlook.
- **Firms and clients that own their workspace.** A business can grant a firm scoped, revocable
  access to its own workspace (engagement), instead of being hosted inside the firm's workspace.
- **Ready for the owner-only pilot (Gate P).** The pilot environment is written as code and
  checked, your data can be exported in full, and a workspace can be deleted. **Nothing is created
  on AWS without your explicit approval.**

## 2. Rules carried from the approved specification (doc 11)
- A personal workspace is its own tenant. There is **no automatic data flow** between personal and
  business workspaces, even with the same owner (§4).
- **Double entry runs underneath** the simplified personal screens (§5). The personal screens never
  bypass the ledger's rules: entries balance, posted entries are immutable, and corrections are
  reversals.
- A business stake, property or investments can be valued by the user. Such values have nature
  `EXPECTED` and are never mixed silently with ledger actuals (§4.3, doc 10 P2).
- The counterpart hint (M5-3) only **suggests**, needs confirmation in the personal workspace, and
  is opt-in (§4.2).
- Engagement grants: approved by the client's owner, time-bound, revocable with immediate effect,
  and permissions are the **intersection** of the engagement scope and the firm role (§3). They are
  audited in both workspaces, and there is no cross-tenant SQL.
- Features per workspace kind are enforced on the server (§5).

## 3. Defaults taken (simplest option; change them any time)
| Question | Default in M5 |
|---|---|
| Personal setup | One action sets up a personal workspace: the `personal` chart of accounts, and fiscal years by calendar year. Approval is off (household policy, already the default). |
| Money accounts and categories | Money accounts are the postable asset and liability accounts; categories are the postable income and expense accounts. Both can be added. |
| Simplified transactions | Three kinds: **spent** (money account → spending category), **received** (income category → money account) and **moved** (between money accounts, e.g. paying the credit card). Each is a balanced two-line entry, posted at once. A mistake is undone by a reversal with a reason. |
| Opening balances | Per money account at a date, against "Opening net worth". |
| Valuations | Property, investments and a business stake can be given a value at a date (nature `EXPECTED`). Net worth uses the latest valuation on or before the date, otherwise the ledger balance. Valuations are versioned and never posted. |
| Net worth | Assets − liabilities at a date, each line labelled actual or valuation, plus month ends for the last 12 months. |
| Personal budget and goals (M5-2) | Reuse M4 budgets (annual, by category) and goals (savings, emergency fund in months of spending, debt payoff). The 12-month projection reuses the goal projection: actuals, then the budget or the 3-month run rate. |
| Pilot environment (M5-5) | Terraform only, validated in CI (`fmt`, `validate`, `tflint`, `checkov`) and **never applied** without approval; backup/restore drill runbook against the local stack. |
| Data export (M5-6) | One ZIP with JSON per table of the workspace, plus document files, and a manifest with hashes. Deletion: a request, then confirmation by the owner with a recent sign-in, then an audited purge after a 30-day grace period (configurable). |
| Charts and design | SVG drawn in React, as in M3–M4. The visual design will change later (owner, 2026-11-10). |

## 4. Order and approach
| # | Item | Issue | Approach |
|---|---|---|---|
| 1 | M5-1 Personal workspace UX | #74 | `personal` module: setup, money accounts and categories, simplified transactions over the ledger, opening balances, valuations, net worth, spending by category; personal screens. |
| 2 | M5-2 Personal budgets, goals, projection | #75 | Personal budget and goal templates on the M4 modules; 12-month personal cash projection. |
| 3 | M5-3 Counterpart hint | #76 | Opt-in link between a business and a personal workspace of the same user; suggested personal entry for a business payment to the owner, confirm-only. |
| 4 | M5-4 Engagement grants | #77 | Grants from a client workspace to a firm, scope intersection, revocation, audit in both workspaces; the firm portfolio includes granted clients. |
| 5 | M5-5 Pilot environment IaC | #78 | Terraform for the pilot (separate account, EU region, encryption, backups, monitoring), never applied; restore drill runbook. |
| 6 | M5-6 Export and deletion | #79 | Full workspace export; deletion request, confirmation and purge. |
| 7 | M5 report | — | Evidence, Gate P checklist and owner items. |

## 5. Acceptance (from doc 11 §9 and backlog §M5)
- No route returns personal data in a business context or the reverse, including dashboards,
  exports and notifications.
- Personal transactions always produce balanced, posted entries; corrections are reversals.
- Net worth labels valuations as `EXPECTED` and equals the ledger balances where there is no
  valuation.
- An engagement is limited to its scope; revoking it makes the next request return 404 and removes
  the client from the firm portfolio.
- The export contains every row of the workspace (verified by counts and hashes); a deleted
  workspace leaves no rows behind after the purge.
