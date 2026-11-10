# ADR-0032: Personal budgets, goals and the 12-month projection are planning data, never postings
Status: **Proposed** (M5-2; awaiting product owner review in PR) · Date: 2026-11-10

## Context
Doc 11 §5 asks for a household budget, savings, emergency-fund and debt-payoff goals, and a simple
12-month projection in personal workspaces. The business budget (M4-1) has preparation, approval
and versions, which a household does not need. Figures must keep their nature (doc 11 §4.3).

## Decision
- **Monthly budget per spending category** (`personal_budget_amount`, nature BUDGET). Setting a new
  amount supersedes the one in force from that month; a trigger allows only marking a row
  superseded, so the history stays. There is no approval step.
- **Goals** (`personal_goal`): savings (reach an amount in chosen accounts by a date), emergency
  fund (hold a number of months of average spending) and debt payoff (bring chosen loans to zero
  by a date). Goals can be retired, not edited or deleted (trigger enforced).
- **Evaluation is deterministic code**, from ledger balances:
  - pace is the average monthly change over the last 3 complete months;
  - needed is the gap divided by the months left;
  - projected is today's figure plus pace times months left;
  - status is on track, at risk (within 5% of the target) or off track.
- **The projection** starts from cash (asset accounts without a valuation) and adds, for each of
  the next 12 months, the 3-month average income less the budget (or the 3-month average spending
  for categories without one). A month that uses only budgets has nature BUDGET, otherwise
  FORECAST, and the first month that would go below zero is flagged. Moves between the person's own accounts are not projected.
- Nothing here posts to the ledger; the ledger stays the record of what happened.

## Consequences
- A household gets a usable plan with no workflow. A business that needs approvals uses the M4
  budget, which personal workspaces do not show.
- The projection is deliberately simple (no seasonality, no interest). Recurring transactions or
  loan schedules can feed it later, still as FORECAST.
