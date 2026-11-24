# ADR-0019: Payment schedules for obligations and loans: conventions and versioned terms
Status: **Proposed** (M3-4; awaiting product owner review in PR) · Date: 2026-11-04
## Context
The 13-week forecast (M3-7) needs the dated cash flows of recurring obligations (rent, payroll,
subscriptions) and of loans, each with its nature (doc 10 §3.2). Loan schedules must match
reference amortisation tables for annuity, linear and bullet loans under ACT/360, ACT/365 and
30/360 (AC-CW8). Banks differ in the details, so the conventions we use must be stated.
## Decision
- **Recurrence:**
  - weekly (on the start date's weekday), monthly, quarterly or yearly, every N periods;
  - on a day of the month, clamped to the month's last day (31 means the last day);
  - an optional end date;
  - moved to a business day with NONE, FOLLOWING, MODIFIED FOLLOWING or PRECEDING.
  - Business days are Monday to Friday, minus the entity's holiday list. Holidays are data, and
    none are built in, because none have been verified.
- **Loans:**
  - **Payment dates:** payments fall every 1, 3, 6 or 12 months from the drawdown date, counted
    from that date (so 31 Jan gives 28/29 Feb, then 31 Mar). The maturity must be a whole number
    of periods away.
  - **Interest:**
    - it accrues between the unadjusted payment dates;
    - payments are made on the adjusted dates (MODIFIED FOLLOWING by default);
    - each period's interest is balance × rate × days ÷ basis, rounded to cents (HALF_UP) once.
  - **Day counts:**
    - ACT/360 and ACT/365 (fixed) count actual days;
    - 30/360 is the ISDA bond basis: day 31 counts as 30, and the end day 31 counts as 30 when
      the start day is 30 or 31.
  - **Annuity:** a level payment P·r/(1−(1+r)^−n) with the nominal periodic rate r = annual rate ×
    months ÷ 12, rounded to cents. Principal = payment − interest.
  - **Linear:** equal principal, rounded to cents.
  - **Bullet:** interest only, with all the principal at maturity.
  - **Interest only, then annuity:** the annuity runs over the remaining periods.
  - **Last instalment:** it repays the balance left, so the principal always totals the amount
    borrowed exactly.
  - **Variable rates:** the rate is an assumed reference rate plus the margin, stored on the
    instrument until scenarios supply it (M5). Interest on a variable rate is therefore EXPECTED;
    on a fixed rate it is COMMITTED, as principal always is.
  - **Facilities:** overdrafts and revolving facilities have a limit only, which will count towards
    liquidity in M3-7, and no schedule.
- **Versioned terms:**
  - Obligations and loans are versions in a series. A change supersedes the current version and
    adds the next; retiring supersedes without a successor.
  - A database trigger allows no other change and no deletion.
  - Flows carry their version ID, so a forecast run can pin, and later reproduce, exactly the
    terms it used (ADR-0017).
## Consequences
- The schedules are checked against reference tables computed independently with exact fractions.
  The 30-year example matches the widely published payment of 1,264.14 for 200,000 at 6.5%.
- A loan whose bank uses another convention (for example, interest accruing to the adjusted date,
  or an annuity recalculated each period from actual days) will differ by cents. Adding a
  convention is a reviewed code change, with its own reference table.
- Irregular first periods, grace periods other than interest-only, fees, and repayment holidays
  are not modelled yet.
## Alternatives considered
- **Storing generated schedule lines:** redundant with immutable terms, and they could drift from
  the generator.
- **RRULE strings:** more general but harder to validate and explain; the structured fields cover
  the cases in doc 10 §3.2.
