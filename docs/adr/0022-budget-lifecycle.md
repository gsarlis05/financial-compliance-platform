# ADR-0022: Budget versions, approval with segregation of duties, database-enforced immutability
Status: **Proposed** (M4-1; awaiting product owner review in PR) · Date: 2026-11-04
## Context
Doc 10 §7 and AC-BU1 ask for budgets with versions (DRAFT → SUBMITTED → APPROVED → LOCKED, and
SUPERSEDED), revisions as new versions with reasons, the original and current budget both kept,
approval with configurable segregation of duties, and approved versions that are immutable at the
database level. The `workflow` module (generic approvals) does not exist yet.
## Decision
- **Own tables in `budgeting`:** budget (entity, fiscal year, type, optional dimension value),
  version, line (taxonomy line *or* account, optional dimension value, phasing method) and one
  amount per month (nature BUDGET, checked by the database). An append-only event table records
  the approval trail. Quarter and year totals are computed from months, never stored.
- **The lifecycle is enforced by triggers, not only by code.**
  - A version starts as a draft and is never deleted.
  - Each allowed transition may change only its own columns: submit, return to draft, approve,
    lock, supersede. Anything else, including editing an approved version, is refused.
  - Lines and amounts can change only while their version is a draft. The trigger share-locks
    the version row, so a submission and an edit can never interleave.
  - A budget's fiscal year, type and scope never change.
- **Submission stores a canonical hash of the lines;** approval checks it again.
- **Segregation of duties:** on by default per entity. The submitter cannot approve. The
  database rejects an approval with `sod_applied` and approver = submitter. Switching it off
  needs `budget.settings.manage` and is audited. Each approval records whether SoD applied.
- **Revisions:** only from the current (approved or locked) version, with a reason. At most one
  open (draft or submitted) version per budget (partial unique index). Approving a revision
  supersedes the previous current version in the same transaction. The original budget is the
  first version ever approved.
- **Locking** marks the year's baseline. Revisions are still possible afterwards.
- **Permissions:** `budget.read` (all reading roles), `budget.edit` (preparers),
  `budget.approve` and `budget.settings.manage` (finance manager, partner, owner).
- **Planning never imports the ledger.** Fiscal years and dimension values are read through
  `reporting`. Same-entity composite foreign keys tie budgets to the ledger's fiscal years,
  accounts and dimension values. A new ledger migration adds the `(legal_entity_id, id)` key on
  dimension values that this needs.
## Consequences
- An approved budget cannot be changed by a bug, a script or direct SQL as the application role.
- When the `workflow` module arrives, budget approval can move onto it without a data change:
  the version columns and events stay the record.
- Department-scoped owners (AC-BU6) and phasing methods come in M4-2. Lines already store the
  method and its parameters.
