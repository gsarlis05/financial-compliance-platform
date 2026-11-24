# ADR-0044: Depreciation begins when an asset is available for use; tax capital allowances are kept separately
Status: **Proposed** (M6F-3, #148; awaiting product owner review in PR) · Date: 2026-11-15

## Context
Owner decisions D1–D3 (2026-11-15): simplified forecasts start depreciation the month after
purchase by default, with the commencement and method selectable; actual accounting follows IFRS,
where IAS 16.55 says depreciation of an asset begins when it is available for use; accounting
depreciation and tax capital allowances are kept separately. The M6-1 register started every
asset the month after acquisition.

## Decision
- **Register (actual accounting).** Each asset has an **available-for-use date** (default: the
  acquisition date) and a **commencement policy**:
  - `PRORATA_DAYS` (default for new assets): from the available-for-use date; the first month is
    depreciated for the days in use over the days in the month, and the schedule runs one month
    longer so the full useful life is used;
  - `NEXT_MONTH`: from the month after (the M6-1 convention; every existing asset keeps it, so
    no schedule changes);
  - `FULL_MONTH`: a full month from the available-for-use month.
  The method (straight-line or declining balance) is chosen per asset as before. Commencement
  and method lock with the other terms once depreciation is prepared. Every schedule states its
  convention.
- **Tax capital allowances.** Per entity, **allowance classes** with an annual rate, a first-year
  rule (full year, months in use, or none) and the tax year from which the rate applies, entered
  with their **source** (law and article, or the adviser's note). Classes are versioned by
  effective date and never changed or deleted (database). **No classes or rates are built in**:
  none has been verified for the platform (owner decision #93; Cyprus wear-and-tear rates are an
  item for the tax professional, #154).
- **Allowance schedules** by tax year: cost × the rate in force at the start of the year, capped
  at the tax written-down value; the first-year rule in the year of first use; none in the year of
  disposal. Balancing allowances and charges on disposal are **not modelled** and the schedule
  says so. Allowances never touch depreciation, book values or journal entries; an asset's
  allowance class can be set or changed after depreciation is prepared (audited), because it is
  tax data.
- **Projections.** New capex drivers: `capex_start` (months after the month of spend; default 1,
  the month after, per D1), `capex_db_rate` (declining balance a year; 0 = straight-line) and
  `capex_allowance_rate` (tax allowance a year, used by the tax calculation in M6F-5). Assumption
  sets made before these drivers use their defaults, so their projections do not change.

## Consequences
- New assets follow IAS 16 by default; the convention is visible on each schedule.
- Capital allowances feed taxable profit (M6F-5) through `capital_allowance_plan`.
- Deferred tax on the difference between book value and tax written-down value is computed in
  projections (M6F-5); in the books it remains a manual entry until a later milestone.
