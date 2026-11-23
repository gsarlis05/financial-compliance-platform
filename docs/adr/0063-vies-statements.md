# ADR-0063: VIES statements recorded by the owner and reconciled to Boxes 8A and 8B
Status: **Accepted** (V1-2g, #218; brief 25 §4) · Date: 2026-11-23

## Context
Supplies of goods and services to businesses in other member states are reported twice:
- in the VAT return, in Boxes 8A (goods) and 8B (services);
- in monthly recapitulative (VIES) statements, per partner.

The owner's specification asks for the two to be reconciled, with timing differences,
corrections and rounding shown, and triangular transactions kept separately identifiable. The
platform never submits anything.

## Decision
- **Statements are recorded as filed** (`tax_vat_vies_statement`, `tax_vat_vies_line`).
  - A statement holds the month, kind (original or correction), filing date, submission
    reference and an optional note.
  - Each line is one partner: country, VAT number, goods, services and triangular amounts.
  - One active original per month.
  - Statements and lines are never edited or deleted. A wrong statement is voided once, with a
    reason, and lines are added only to an active statement (database guards).
- **Partners are matched** on country and VAT number, ignoring spaces, punctuation and the
  country prefix (EL for Greece).
- **The reconciliation is read live** (`report.vies_reconcile`), against the report's frozen
  lines and its final return:
  - **Each partner:** the EU goods and services supplies in the books against the statements of
    the period's months. Each partner is classed as one of:
    - **agrees** (`MATCH`);
    - **rounding** (`ROUNDING`, under one euro);
    - **not in a statement** (`NOT_FILED`);
    - **not in the books** (`NOT_IN_BOOKS`);
    - **triangular only** (`TRIANGULAR`);
    - **a difference to explain** (`DIFFERENCE`).
  - **Timing:** months with EU supplies in the books but no statement recorded are listed.
  - **Totals:** the statements' goods and services against Box 8A and Box 8B (their exact
    amounts), with the difference.
  - **Triangular:** triangular amounts are totalled apart and compared with no box. Their
    treatment in the return is for a tax professional to confirm.
- **Corrections:** for a month, the latest statement filed replaces the earlier ones. A
  correction is taken to carry the month's full corrected values. **This is an assumption to be
  confirmed by a Cyprus tax professional (#93).** If corrections carry only the changes, the
  comparison must add them instead.
- The comparison is never part of the report's fingerprint, and never blocks a review: a
  statement can be filed after the return.

## Consequences
- The owner sees at once whether the VIES statements and the return agree, and why not.
- No VIES data is sent anywhere, and partners' VAT numbers are not checked against the
  Commission's VIES service.
