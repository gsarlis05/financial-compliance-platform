# ADR-0052: KPI library CORE@1.1 and KPIs on projected and scenario figures
Status: **Proposed** (M7-6, #181; awaiting product owner review in PR) · Date: 2026-11-16

## Context
Doc 10 §5.1 lists net debt / EBITDA (LTM) and DSCR among the stability KPIs, and inventory and
receivables turnover among the efficiency KPIs. M4-4 (ADR-0025) left the first two out because they
need a last-twelve-months EBITDA and the debt to be serviced. Doc 10 §8 also asks that a scenario's
effects be shown on KPIs, and the M7 brief (§3) that KPIs on projected and scenario months use the
same definitions as on actuals.

## Decision
- **CORE@1.1** = the 19 KPIs of CORE@1.0, unchanged, plus four (worked examples and
  not-meaningful conditions in the library file):
  - **Net debt / EBITDA:** (borrowings − cash) at the period end over EBITDA of the 12 months to
    the period end; not meaningful when that EBITDA is zero or negative; negative means net cash.
  - **DSCR:** (EBITDA − income tax, both over the 12 months to the period end) over debt service =
    interest of those 12 months + the debt due within 12 months of the period end (the current
    portion of borrowings, IAS 1.69). Income tax expense stands for cash taxes, and the current
    portion for the principal due; both are stated in the convention. Not meaningful without debt
    service.
  - **Receivables turnover** and **inventory turnover:** revenue (resp. cost of sales) of the
    period, annualised, over the average balance; not meaningful when the average is zero.
- A new reference function **`ltm_flow(key)`**: the 12 months to the period's last month (the KPI
  engine already loads 12 months before the period, so no new data is read). Custom KPIs may use it.
- New KPI sets use CORE@1.1. CORE@1.0 stays in the reference table, so earlier KPI sets and the goals
  that measure a CORE@1.0 KPI keep their definition version (doc 10 §5.2).
- **KPIs on projected and scenario figures** (`GET …/projected-kpis?year=`): every CORE@1.1
  definition is evaluated, unchanged, on a projected year. Each projection line becomes a
  pseudo-account carrying its taxonomy code and section, so formulas read the same keys as on
  actuals. Values are `FORECAST` for an approved set and `HYPOTHETICAL` for a shared scenario,
  shown next to its base. A KPI that needs months the projection does not hold (the same period a
  year earlier, the 12 months to the period end, three months of cash before it) is not meaningful
  with that reason, never computed on missing data.

## Consequences
- The DSCR convention is an approximation commonly used by lenders; a covenant definition from a
  loan agreement may differ and can be set up as a workspace KPI (M4-5).
- Projected KPIs inherit the projection engine's status, `PENDING_PROFESSIONAL_REVIEW`.
