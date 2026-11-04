# Obligations, loans, tax payments and holidays

**Cash & planning → Obligations, loans & tax** records the payments you already know about. The cash
forecast (Milestone 3) uses them, and each amount is labelled with its nature:
- **Committed:** contractually due, such as rent under a lease, loan principal, or interest at a
  fixed rate;
- **Expected:** likely but not contractual, such as an estimated utility bill, or interest at a
  variable rate (the reference rate is an assumption).

## Recurring obligations
1. Enter a name, a category, whether it is a payment or a receipt, and the amount.
2. Choose how often it recurs:
   - weekly, monthly, quarterly or yearly;
   - every N of these;
   - and, except for weekly, the day of the month.

   Day 31 means the last day of the month.
3. Choose what happens when the date is not a business day: keep the date, the next business day,
   the next business day in the same month, or the previous business day.
4. Tick **Contractual** if it is committed.

**Change** saves a new version, and the previous version stays in the history. **Retire** stops
the obligation.

## Loans and facilities
- **Loans:** enter the principal, start date, maturity, repayment type, payment frequency, day
  count and rate.
  - The repayment types are:
    - annuity: level payments;
    - linear: equal principal;
    - bullet: all principal at maturity;
    - interest only, then annuity.
  - Rates are entered as percentages (5 means 5%). A variable rate needs the reference rate's
    name, an assumed value for it, and the margin.
  - **Schedule** shows every instalment: due date, interest, principal and the balance after it.
  - The maturity must be a whole number of payment periods after the start date.
- **Overdrafts and revolving facilities** have a limit only. Their limits count towards available
  liquidity in the forecast.

The conventions used (day counts, rounding, payment dates) are in ADR-0019.

## Tax payments
Enter each tax payment by hand: VAT, corporate tax instalments, special defence contribution,
social insurance, PAYE or other. Give it a period label (e.g. 2026-Q3), a due date, an amount and
its nature:
- **Committed** when it has been assessed or returned;
- **Expected** when it is an estimate.

No due dates are built in or pre-filled. Templates with Cyprus due dates will be added only after
a tax professional has verified them (decision #93). **Mark paid today** records the payment
date: a paid tax payment no longer counts as a future flow, because the bank statement shows the
actual payment. **Change** saves a new version, for example when the assessed amount replaces
the estimate.

## Holidays
No public holidays are built in. Add the days that are not business days for this entity; payment
dates then move as each obligation's or loan's setting says.

## Upcoming flows
The last section lists every flow due in the next 90 days with its nature. Where a date was moved
to a business day, the original date is shown in brackets.
