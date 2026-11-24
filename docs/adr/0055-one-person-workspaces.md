# ADR-0055: One-person workspaces: self-approval, recorded and allowed only for one member
Status: **Accepted** (V1-1, #207; owner decision 2026-11-22, brief 24) · Date: 2026-11-22

## Context
Version 1 is used by the owner alone (brief 24). Five steps require a second person: approving
a journal entry, approving a period unlock (two approvers), approving a budget version, deciding a
workspace KPI and finalising a report pack. VAT returns (V1-2) will add a sign-off. With one
person these steps cannot be completed. The owner chose: "I approve my own work, and every such
approval is recorded."

Segregation of duties stays the default. The risk to manage is a self-approval in a workspace
where a second person could have approved, whether through a bug, a forged request or a direct
database change.

## Decision
- **A workspace setting, `one_person`** (`tenancy_tenant.one_person`), off by default, changed
  only by someone with `tenancy.members.manage`, after a recent sign-in, and audited.
- **It is in force only while the workspace has exactly one active member and no active
  engagement grant.** `tenancy_one_person(tenant)` gives the database's answer. The database
  also refuses:
  - turning the setting on with a second member, a pending invitation or an active grant;
  - a second active membership, a new invitation or a new grant while the setting is on.

  The services refuse the same, with the reason.
- **Self-approval is explicit and recorded.** Each table records whether the approver was the
  preparer: `self_approved` on journal entries, period unlocks, budget versions, custom KPIs and
  report packs. The audit event of the approval carries `self_approved`. Screens show
  "Self-approved (one-person workspace)", and pack exports print it next to the status.
- **The database decides.** `tenancy_self_approval_guard()` refuses `self_approved = true`
  outside a one-person workspace. The existing rules now allow a preparer to approve only when
  the row is marked self-approved:
  - journal entries gain the constraint `approver ≠ preparer unless self-approved`;
  - the unlock, budget, KPI and pack rules are relaxed the same way, and nowhere else.
- **Period unlock:** in a one-person workspace the requester's own approval opens the period at
  once: one approval, no second approver, marked self-approved.
- **Budgets:** the entity's segregation-of-duties setting is left as it is. A self-approval is
  stored with `sod_applied = false` and `self_approved = true`.

## Consequences
- A one-person owner can run every workflow alone, with a visible trail of what they approved
  themselves.
- Adding a person requires turning the setting off first. From then on every earlier rule
  applies at once. Earlier self-approvals stay marked as such.
- Nothing changes for workspaces that do not turn it on: the earlier tests still pass unchanged.
