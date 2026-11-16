# ADR-0048: Goals use the published projection as the forward reference and the approved budget as a separate benchmark
Status: **Proposed** (M6F-7, #152; awaiting product owner review in PR) · Date: 2026-11-16

## Context
Owner decision D7 (2026-11-15): the latest approved, published projection is the primary
forward-looking reference for expected goal achievement; the approved budget stays a separate
benchmark; actual vs budget, actual vs forecast and projected vs goal are shown; approved goals
are never changed automatically when forecasts change. Since M6-5 a goal's likely outcome used
the published projection where it covered the remaining months, otherwise the budget. But the
evaluation then lost the budget: its contribution analysis compared the outcome with the plan in
the evaluation's inputs (labelled "budget"), which was the projection's remaining months when a
projection was published, and not the approved budget.

## Decision
- An evaluation pins **three plans** in its inputs: the forward reference (`plan`: the published
  projection, else the budget, as before), the **approved budget** for the goal's period
  (`budget`), and the published projection covering the **months to date**
  (`projection_to_date`).
- New figures (engine `GOAL_EVAL` version 2), with natures:
  - `goal.benchmark`: the budget for the period and for the months to date; the published
    projection's forecast and the actual over the months to date that it projected (a projection
    starts at its cut-over, so it usually covers only part of the period to date);
  - `goal.variance`: actual − budget to date; actual − forecast over the projected months;
    likely outcome − budget for the period; likely outcome − goal.
  Each is "not meaningful" with the reason where the budget does not cover the months or no
  published projection covers a month to date. Balance (cash) goals keep the 13-week forecast.
- The **contribution analysis** compares with the approved budget for the whole period (or the
  same months a year earlier), never with the projection.
- **Goals never change by themselves.** Evaluations, projections, rolling forecasts and budgets
  only produce evaluations; a goal changes only by a person's revision (a new version). Tested:
  a newer projection run and published leaves the goal's versions identical.
- Screens: the goal's evaluation shows the four comparisons in one table; actual vs budget by
  month is the budget's variance view (M4-3); actual vs any projection by month is the
  projection's "Against actuals" (M6F-6).

## Consequences
- Version 1 evaluations stay as stored; a new evaluation uses version 2.
- When a projection was published, the contribution analysis now uses the budget (a correction).
