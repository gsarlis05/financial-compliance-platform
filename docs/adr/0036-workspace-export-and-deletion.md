# ADR-0036: A workspace can be exported in full and deleted for good, by its owner, with a grace period
Status: **Proposed** (M5-6; awaiting product owner review in PR) · Date: 2026-11-10

## Context
Gate P needs the owner's data to be portable and removable: a full export, and a deletion that
leaves nothing behind (doc 11 §9; M5 brief §3 and §5). Two rules of the platform pull the other
way: posted entries and the audit trail are immutable (database triggers refuse changes and
deletes), and every table is isolated per workspace by row-level security.

## Decision
- **Export: one ZIP, built from the database catalogue.**
  - A JSON-lines file for **every table that has a workspace column**, so a new module's tables
    are included without anyone remembering to add them.
  - The files of the workspace's documents, the members' names, and `manifest.json` with the
    row count and SHA-256 of every file.
  - Rows are read inside the workspace's row-level security context and filtered by workspace
    as well. Owners and firm partners only, with a recent sign-in, never through an engagement
    grant. Each export is recorded in the audit trail.
- **Deletion: two steps and a grace period.**
  1. An owner requests it. Nothing changes.
  2. An owner confirms with a recent sign-in and the workspace's exact name. The purge is due
     after `WORKSPACE_DELETION_GRACE_DAYS` (30). The workspace stays usable, every page shows
     the date, and an owner can cancel.
  - Only the **owner role** can request, confirm or cancel (a partner cannot).
- **Purge: a maintenance job with the schema-owner role** (`tenancy_purge_workspaces`, daily).
  In one transaction it switches off the user triggers on the workspace's tables, deletes every
  row of that workspace (children before parents where a foreign key cannot be deferred),
  deletes the workspace row, switches the triggers back on, and **proves that no row is left**
  before it commits. Document files are removed from storage. The application's runtime role
  cannot do any of this.
- **What remains** is one row in `tenancy_workspace_deletion`, a global table: the workspace ID,
  the IDs of who requested and confirmed, the dates, and the number of rows removed per table.
  No names and no financial data.

## Consequences
- Immutability holds for every user action. Deleting the whole workspace is the one exception,
  it is reserved to a job that users cannot start, and it leaves a record.
- Switching triggers off takes a short lock on those tables for all workspaces while the purge
  runs. That is acceptable for the pilot; a larger system can purge in a quiet window.
- A document under a storage retention lock cannot be removed before the lock ends. It is
  counted as retained in the record and expires with the bucket's rules.
- Backups still contain a deleted workspace until they expire (35 days daily, one year
  monthly). The privacy notice must say so; restoring a backup must be followed by the purge
  job, which reads the same global table.
- The export is built in memory, which suits the pilot. A very large workspace will need a
  background export with a download link.
- Other workspaces may keep IDs that pointed at the deleted one (an engagement, a counterpart
  link). They resolve to nothing and give no access.
