# ADR-0028: In-app alerts, raised on a change of state
Status: **Proposed** (M4-7; awaiting product owner review in PR) · Date: 2026-11-10

## Context
Doc 10 §6.2 item 8 and §7, with AC-GO4, ask for alerts in three cases:
- a goal's status crosses into at risk or off track;
- a goal's threshold breach is forecast;
- a budget line overruns its thresholds, or is unfavourable for 3 consecutive months.

An alert must not be raised again while its condition is unchanged. The M4 brief says alerts are
in-app only (email later), users acknowledge them, and they are kept.

## Decision
- **Module.** Alerts live in `dashboards`, which was set aside for "alert rules and alerts" and
  will show them on the CFO dashboard in M4-8.
- **De-duplication by key.** Each watched condition has a key, such as `goal:<id>:status` or
  `budget:<id>:<line>:overrun`.
  - `dashboards_alert_state` holds the key's last observed state.
  - An alert is raised only when the state **changes into** an alerting state, and the state row
    is locked while this is decided.
  - Returning to a normal state resets it silently, so a later change raises a new alert.
  - A unique key on (entity, key, change number) makes a duplicate impossible.
- **Sources.**
  - **Goals:** `goals` publishes an evaluation listener (`on_evaluation`) that `dashboards`
    registers, so `goals` never imports `dashboards`.
    - The status alert is a warning when the goal is at risk and critical when it is off track.
    - A breach alert (critical) is raised when a threshold goal's worst point breaches it. It says
      whether the breach is in actuals or forecast.
  - **Budgets:** `POST alerts/check-budgets` checks each budget's current approved version for a
    month (default: the last complete month).
    - An **overrun** is a year-to-date variance that is unfavourable and reaches both M4-3
      thresholds (amount and %).
    - A **trend** is the last 3 months each unfavourable.
- **Visibility and acknowledgement.**
  - Goal alerts need `planning.read` to see; budget alerts need `budget.read`.
  - Acknowledging needs the new `alert.acknowledge` permission (preparers, reviewers and above).
  - An acknowledgement records who and when, with an optional note, and happens once.
  - A trigger refuses any other change and any delete. Everything is audited.

## Consequences
- AC-GO4 is met for every evaluation. Budget checks run when asked for: from the Alerts page, or
  later from the dashboard. A scheduled check and email delivery are left for M8 (management
  reporting and alerts by email).
- Department budget owners (`budget_holder`) do not see alerts in M4, because they have no
  `planning.read`.
