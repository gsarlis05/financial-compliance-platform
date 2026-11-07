# ADR-0026: Custom KPIs and operational metrics
Status: **Proposed** (M4-5; awaiting product owner review in PR) · Date: 2026-11-07
## Context
Doc 10 §5.2 and §5.3, with AC-KP4 and AC-KP5, ask for the following:
- users can write KPIs in the formula language, after validation (syntax, units, references and a
  dry run);
- personal KPIs need no approval;
- workspace KPIs need approval, are versioned, and historical values reference the version used;
- operational (non-ledger) metrics are entered, versioned, audited and labelled in every display.
## Decision
- **Custom KPIs are tenant data** (`kpi_custom`), one row per version.
  - **Personal** versions are ACTIVE at once.
  - **Workspace** versions are SUBMITTED, then APPROVED or REJECTED by someone other than the
    author with `kpi.definition.approve`. This is checked in the service and by a database
    constraint.
  - **Content never changes after saving.** A trigger allows only the documented status changes
    and the decision fields, and versions are never deleted.
  - **One pending version** per key at a time.
- **Workspace KPIs in a KPI set:** the approved ones are snapshotted into the KPI set run (formula,
  name, display, direction, version), so a value's definition id is
  `WORKSPACE:<KEY>@<version>` and the run reproduces even after a later version.
- **Personal KPIs are never stored in a shared run.** Calculation results can be read by anyone
  with `planning.read`, so they would leak. Instead, they are evaluated when the owner asks, on a
  stored run's pinned inputs (watermark, account mapping and operational values), and returned
  only to the owner.
- **Validation:**
  - compile with the reference functions;
  - check the unit against the display;
  - check every taxonomy key literal against the taxonomy, and every metric literal against an
    operational metric of the right unit;
  - dry run on the last complete month with current data.
- **Operational metrics** (`kpi_operational_metric`, `kpi_operational_value`):
  - entered with `kpi.operational.manage`;
  - one current value per month, with a correction superseding the previous one (database trigger;
    nothing is deleted);
  - LAST metrics use the period's last month, SUM metrics add the months, and a missing month
    makes the value not meaningful;
  - the values a run uses are snapshotted into its inputs;
  - lineage kind MANUAL, and the result is tagged `NON_LEDGER`; the API exposes `non_ledger`, and
    the UI labels it in text with a dashed outline, never colour alone.
## Consequences
- Changing a standard-formula convention (e.g. DPO on purchases) is done by proposing a workspace
  KPI under a new key. Overriding a library key is refused, because library versions never change.
- Operational metrics are entered by hand only. CSV import can come later.
