# ADR-0061: VAT schedules, reconciliation to the ledger, and the export formats
Status: **Accepted** (V1-2e, #216; brief 25 §3–§5) · Date: 2026-11-23

## Context
The owner's specification asks for:
- schedules behind the return: sales, purchases, EU trade, reverse charge, imports, adjustments
  and exceptions;
- a reconciliation of the VAT control accounts and of the return to the ledger;
- a PDF, an Excel workbook with named sheets, and a CSV of every line's box contributions;
- a coverage matrix.

## Decision
- **Schedules are derived, not stored.** They are computed on reading from the report's frozen
  lines (`report.schedules`): one row per entry and VAT code, with the party, country, VAT
  number, invoice number, amounts and box contributions, plus totals.
  - **Imports:** the import category.
  - **Reverse charge:** EU goods acquisitions, the three reverse-charge categories and the old
    `RC` code.
  - **Sales and purchases:** every other category.
  - **EU trade:** EU supplies, acquisitions and EU services received, typed as goods or
    services, supplied or received.
  - Adjustments and exceptions come from the report itself.
  - Because the lines are frozen from the review on, the schedules are too.
- **Balances are captured at generation.** Each VAT control account's balance before the period
  and at its end is captured in the snapshot (`balances`).
  - They are not part of the figures' fingerprint. A posting in an earlier period changes an
    opening balance, but not this period's return, so it does not block the review.
  - The reconciliation (`report.reconcile`) is computed on reading, so it includes the approved
    adjustments.
- **Reconciliation:**
  - **For each VAT account:** opening + the period's VAT + settlements = closing, with anything
    unexplained shown. Output VAT reads credit-positive, input VAT debit-positive.
  - **Bridges, one for output VAT (Boxes 1 + 2) and one for input VAT (Box 4):** the ledger's
    VAT, minus VAT lines in no box, plus adjustments, equals the return. Anything unexplained is
    shown, and the report says whether everything reconciles.
  - Payments, refunds and the settlement entry are shown apart from Box 5.
- **Exports:**
  - **Excel:** sheets Summary, Sales, Purchases, EU Trade, Reverse Charge, Imports,
    Adjustments, Reconciliation, Exceptions and Tax Code Mapping, plus Codes and Lines. Amounts
    are numbers with a number format, and every table has a filter.
  - **PDF:** the same sections. Every page carries the company, the period, the version and the
    page number.
  - **CSV:** UTF-8, one row per line, with stable ids, the line's fields, the mapping, the rule
    and the rules version, and one column per box. Text is made formula-safe, as in Excel.
  - Every export is audited.
- **The coverage matrix** (`docs/vat/coverage.md`) lists what is covered, excluded and not
  supported, with sources and tests. A test checks that it matches the box rules data.
- `money()` never prints "-0.00".

## Consequences
- Every figure in the return can be followed to a schedule row, a line and an account, and the
  return agrees with the ledger or says why not.
- Still to come: imports with customs data and duplicate checks (V1-2f), and the VIES
  comparison (V1-2g).
