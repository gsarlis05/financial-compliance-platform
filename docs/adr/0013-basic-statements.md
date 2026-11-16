# ADR-0013: How the basic statements are built (equity before year end, cash-flow classification)
Status: **Proposed** (M2-8; awaiting product owner review in PR) · Date: 2026-11-04
## Context
M2-8 produces a P&L, balance sheet and indirect cash flow statement from the `reporting.actuals`
read model and the account → taxonomy mapping (M2-6). Two questions need a rule. First, profit is
not closed to retained earnings until year end (M2-9), so how does equity show it? Second, the
taxonomy (IFRS_SME_CY 1.0) says where a balance goes on the balance sheet, but not which cash-flow
activity its movement belongs to.
## Decision
- **Management statements, not statutory.** Every screen and export says so. Statutory IFRS
  statements are M10.
- **Signs.** Balance-sheet rows show natural balances: assets as debits, equity and liabilities as
  credits. P&L rows show their effect on profit, so income is positive and expenses negative. Every
  subtotal is then a plain sum.
- **Equity before year end.** The balance sheet adds two computed equity rows from the income and
  expense accounts: *profit (loss) for the year to date* (since the start of the fiscal year
  containing the balance-sheet date) and, only when non-zero, *result of earlier years not yet
  closed*. After the M2-9 close, the second row is zero.
- **Cash flow (indirect).** The statement starts from profit for the period. Each balance-sheet
  line's movement is classified by a versioned rule set per taxonomy version (`CASH_FLOW_RULES`):
  - Operating: working capital, which is inventories, receivables, tax and payables.
  - Investing: property, plant and equipment (cost and accumulated depreciation as one group),
    intangibles and investments.
  - Financing: borrowings and equity accounts.
  - Non-cash: depreciation and amortisation are added back in operating and taken out of the
    investing group whose balance they reduced, so investing shows purchases less disposals.
  - Interest stays in operating, inside profit.

  A test asserts that every balance-sheet line is classified exactly once. That makes the statement
  reconcile to the movement in cash by construction.
- **Checks, always computed and shown.** These are:
  - the balance sheet balances;
  - equity on the balance sheet equals equity from the accounts;
  - the P&L result equals the movement in equity less contributions and distributions;
  - the net cash flow equals the movement in cash.

  A failed check is a defect. It is logged (`metrics.statements_check_failed`) and shown, never
  hidden.
- **Blocking.** An unmapped account with a balance at either end of a period shown blocks the
  statements (409 `metrics.statements.mapping_incomplete`). Its amount would otherwise be missing.
- **Comparatives** are the same dates one year earlier (29 February becomes 28 February).
## Consequences
+ Statements are correct by construction and self-checking. The golden file for Demo Trading pins
  the figures (AC-M2-8).
+ Cash-flow classification is reviewable data in code, versioned with the taxonomy.
− Classification is per line, not per transaction. For example, interest paid cannot be moved to
  financing, and a disposal's proceeds and book value appear together in investing. A later
  taxonomy version can add finer lines.
− Closing entries (M2-9) must be excluded from the P&L of the year they close, or that year's result
  would show as zero. M2-9 has to handle this.
## Alternatives considered
Direct-method cash flow (needs the cash side of every posting classified; deferred to the cash
forecast work in Phase 2). Putting cash-flow classes into the taxonomy JSON (better long term, but
it needs a new taxonomy version, IFRS_SME_CY 1.1; planned together with M10).
