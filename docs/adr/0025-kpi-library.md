# ADR-0025: The KPI library as versioned reference data, computed as calculation runs
Status: **Proposed** (M4-4; awaiting product owner review in PR) · Date: 2026-11-04
## Context
Doc 10 §5.1 asks for a standard library of KPI definitions with these attributes:
- formula;
- unit and direction;
- conventions;
- not-meaningful conditions;
- a worked example.

AC-KP1 to AC-KP3 ask that values:
- match hand-computed figures;
- show "not meaningful" with a reason;
- drill down to the accounts and entries behind them.
## Decision
- **Definitions are reference data**: table `kpi_definition`, seeded from
  `kpi/library/core_1.0.json`, read-only for the runtime role. A library version (`CORE@1.0`) never
  changes once released, so a stored value always names the definition version it used (AC-KP4).
  Workspace and personal KPIs (M4-5) are tenant data in their own table.
- **Formulas use the M3-3 language** with reference functions over the taxonomy:
  - `flow` and `prior_flow` for movements;
  - `balance`, `opening` and `avg_balance` for balances;
  - `days`, `annual_factor` and `burn_3m`.

  A key is a taxonomy section, line or code prefix. Amounts are in each account's natural direction.
  Equity includes the result of years not yet closed.
- **A KPI set is a calculation run** (`KPI_SET`):
  - **Inputs:** the period, the library version, and a snapshot of the account mapping (code,
    section, normal side, P&L or not). Actuals come from `reporting`, pinned to the run's
    watermark.
  - **Outputs:** every value is ACTUAL. Its lineage names the definition, each reference call and
    each contributing account. The run is reproducible (tested).
- **Periods are whole months**, up to 12, because monthly actuals are the read model's grain.
- **Not meaningful:** the language never gives 0 or ∞. Each definition states its own plain reason.
- **Rounding:** values are stored unrounded (20 places) and rounded only for display (doc 10 §2.4).
- **Freshness:** a set reads as out of date when entries were posted after its watermark (checked
  on reading, as for the forecast).
## Consequences
- The library has 19 KPIs. ROA, ROE, net debt/EBITDA and DSCR were optional in doc 10; ROA and ROE
  are included. Net debt/EBITDA (it needs a last-12-months EBITDA) and DSCR (it needs scheduled
  principal) follow when their inputs are modelled.
- Credit sales are not tagged, so DSO uses all revenue. The quick ratio has no short-term investment
  line in the taxonomy.
- Year to date assumes a January fiscal year in the page's presets. Any whole-month range can be
  requested through the API.
