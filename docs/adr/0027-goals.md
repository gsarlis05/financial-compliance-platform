# ADR-0027: Goals: frozen baselines, evaluations as runs, goal-seek and contribution analysis
Status: **Proposed** (M4-6; awaiting product owner review in PR) · Date: 2026-11-07

## Context
Doc 10 §6 and AC-GO1 to AC-GO5 ask for goals on a metric or KPI. Each goal needs:
- a baseline frozen at creation;
- versioned targets;
- evaluations stored as calculation runs: actual to date, likely outcome, gap, required
  performance, status, trend and contribution analysis;
- a deterministic goal-seek that says "not achievable within bounds";
- alerts on status changes (M4-7).

There is no rolling P&L forecast until Phase 3 (M6).

## Decision
- **Metrics.** A goal tracks a formula in the KPI language (M4-3, M4-4), so every figure explains
  itself down to accounts. There are three kinds:
  - **additive** built-ins: revenue, operating expenses, EBITDA, net profit;
  - **ratios**: every library KPI and approved workspace KPI, with the formula version kept on
    the goal;
  - **balance**: cash.
  The window is whole months, at most 24.
- **Baseline (AC-GO1).**
  - At creation a `GOAL_BASELINE` run computes the metric over the same months a year earlier
    (for cash, the balance on the first day).
  - Its value, window and run id are copied unchanged into every version.
  - A change of target is a new version with a reason, and a version's content never changes
    (database trigger).
  - A "change %" target is turned into a value from the frozen baseline, so it is refused when
    the baseline is not meaningful.
- **Evaluation** is a `GOAL_EVAL` run, pinned to the ledger watermark, with these snapshots in
  its inputs:
  - the goal version;
  - the account mapping;
  - operational values;
  - the approved annual budget (its versions and amounts);
  - for cash, the latest 13-week forecast.
  An append-only `goals_evaluation` row keeps the status and gap for alerts and the gap trend.
- **Likely outcome.** Actuals up to the cut-over (the last month end on or before the as-of
  date). The remaining months are then projected in this order:
  1. the current approved annual budget (plan pseudo-accounts per taxonomy line);
  2. otherwise each account's trailing 3-month run rate.

  Balances after the cut-over are held at their latest actual value. Cash goals use the forecast's
  week-end closings. A threshold goal ("stay at or above") is judged on the worst month end or
  forecast week in the window. The method is stated with every outcome.
- **Status:**
  - on track when the outcome meets the target, adjusted for direction;
  - at risk when it misses by at most the materiality (default 5% of |target|);
  - off track otherwise;
  - undetermined when the outcome is not meaningful.
- **Required performance:**
  - Additive goals: the remaining amount, and the required monthly run rate against the
    projected and historical ones.
  - Ratios whose formula is a division at the top level: the numerator needed with the projected
    denominator held, and the denominator needed with the projected numerator held. Both are
    stated.
  - Ratios generally: bisection of a uniform % change of one driver line (default REVENUE,
    chosen per goal or per evaluation) over the remaining months, within ±100%, to 0.01
    percentage points, in at most 60 steps. Otherwise "Not achievable within ±100% of <driver>"
    (AC-GO3).
  - Cash: the first breach and the minimum additional inflow.
- **Contribution analysis (AC-GO5).** The outcome is compared with the budget, or without one with
  the same months a year earlier, in full.
  - Each taxonomy line's effect is the change when only that line takes its outcome values
    (one at a time).
  - For additive metrics the effects add up exactly.
  - For ratios the interaction is shown as an explicit residual.
  - A run invariant checks that the effects plus the residual equal the total.
- **Permissions:** `goal.manage` (preparers and above) to set, change and retire goals;
  `planning.run` to evaluate; `planning.read` to read.

## Consequences
- An evaluation is reproducible from its stored inputs (AC-CF3 applies).
- Projections are deliberately simple until the projections module (M6), and the method is shown
  with every outcome. When rolling forecasts exist, they become the first projection source.
- The golden fixture (AC-GO2) is computed independently in `tests/goals/test_goals.py`. The demo
  sets the six sample goals on Demo Trading. **Sign-off by a finance professional is an owner item.**
- Assumed monotonic behaviour in the driver bisection is documented. A non-monotonic formula can
  report "not achievable" where a solution exists inside the bounds.
