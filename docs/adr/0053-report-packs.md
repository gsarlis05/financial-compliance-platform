# ADR-0053: Report packs as frozen snapshots with a review workflow
Status: **Proposed** (M8-1, #190; awaiting product owner review in PR) · Date: 2026-11-17

## Context
Doc 10 §9, FR-M1 and FR-E3 ask for management report packs that are frozen as reproducible
snapshots, reviewed before they are final, and never changed once final (P5). Doc 10 §7 and FR-B4
require explanations for variances above the thresholds before a pack is final. Threat T30: a pack
must not hold more than the person who generated it may see. The M8 brief (doc 22, approved
2026-11-17) proposes `DRAFT → IN_REVIEW → FINAL`, a reviewer who is not the preparer, and new
versions for corrections.

## Decision
- **One table, `mgmt_reporting_pack`:** a pack per legal entity and period (a month, or the fiscal
  quarter or fiscal year containing a month). Versions of one pack share a `family_id`; a new
  version names the final version it supersedes. The snapshot is stored in the row as JSON.
- **Snapshot:** generating reads the existing reports and runs **under the preparer's
  permissions** and stores plain data: exact decimal strings with their nature, plus references
  (calc run ids, the budget version, the ledger watermark) and a canonical hash. Blocks:
  statements (with the prior year), the variance report of the current approved annual budget
  (month, quarter to date, year to date, full year; against the budget, the original budget and
  the prior year; with explanations), the KPI set for the period, the 13-week cash forecast, the
  latest published projection covering the next 12 months (marked pending professional review)
  and the goals. A block the preparer may not see is stored as `denied`, one without data as
  `empty` with the reason; neither fails the pack. Nothing is recomputed when a pack is read.
- **Workflow:** a draft can be regenerated or retitled and is submitted for review; a reviewer
  (`reports.finalise`) returns it with a note or finalises it. Finalising is refused (409
  `mgmt_reporting.not_finalisable`, with what to do) while a variance in the snapshot needs an
  explanation it lacks, or while the period's statements differ from the snapshot (an entry dated
  in or before the period was posted after generation). Postings for later months do not block.
  This replaces the brief's "a referenced run is stale": 13-week forecasts and KPI sets become
  stale on any posting, so that rule would block every pack once the next month's entries start.
  Each run's stale flag is kept in the snapshot instead.
- **Permissions:** `reports.pack.read` (every role that reads), `reports.pack.prepare` (preparers),
  `reports.finalise` (owner, partner, finance manager). The preparer can never finalise their own
  pack (service and database).
- **Database:** FORCE row-level security and composite tenant keys. A trigger: a pack starts as a
  draft (version 1, or the next version of the final version of the same family, entity and
  period); its entity, family, version, period, origin and preparer never change; a pack in review
  is frozen; `FINAL` needs a reviewer who is not the preparer; a final pack changes only to
  `SUPERSEDED` (when its next version is finalised); nothing is deleted. At most one open version
  per family (partial unique index).

- **Sections (M8-2)** are rendered from the snapshot by pure functions (`sections.py`), so the
  screen and the exports read the same tables; every cell carries its nature. Commentary and risks
  live in two append-only tables (`mgmt_reporting_comment`, `mgmt_reporting_risk`), written only
  while the pack is a draft (database trigger), and copied into a new version.

## Consequences
- Packs read the same for ever, and two renderings of one snapshot are identical (M8-3 exports
  read the same snapshot).
- A correction to a final pack is always a new version; the earlier one stays readable.
- Sections, comparison columns, commentary and risks come in M8-2; exports in M8-3.
