# ADR-0059: The 13-box VAT return from line contributions
Status: **Accepted** (V1-2c, #214; owner decisions 2026-11-23, brief 25) · Date: 2026-11-23

## Context
The owner files the VAT return on the Tax Department's portal and asked the platform to prepare
what the law requires at the end of each VAT period. The owner's specification (brief 25) sets
out the 13 boxes and how each kind of transaction feeds them. V1-2b stored those rules as
versioned data (`CY-VAT-BOXES@1`, ADR-0058), marked unverified. The VAT report of V1-2a showed
the ledger analysis only, with a placeholder for "what the law requires".

## Decision
- **Each line contributes to boxes; the boxes are the sum of the contributions.**
  - A line's kind comes from its account, as in V1-2a:
    - output VAT on an OUTPUT VAT account;
    - input VAT on an INPUT VAT account;
    - otherwise a net sale or net purchase.
  - Its VAT code's category and its kind select the rule. The line's amount is added to every
    box the rule names.
  - Box 3 = 1 + 2 and Box 5 = 3 − 4 are computed, never entered.
- **Every line in the report records its contribution:** the boxes, the rule's source, and
  whether it was mapped, excluded (not a supply, a settlement) or unsupported. The report records
  the version of the rules it used. The screen opens the lines behind any box, with their total.
- **Nothing is guessed.** A line the rules do not support goes into no box and is listed as an
  exception, once per entry, code and kind. The owner checks these with a tax adviser; manual
  adjustments come in V1-2d. Unsupported lines include:
  - exempt items;
  - the value of imports;
  - the old `RC` code;
  - output VAT on a zero-rated code.
- **Partial recovery:** Box 4 takes the line's amount, which is the recoverable VAT. The rate
  check adds the non-recoverable VAT back before comparing with the code's rate, so partial
  recovery is not reported as an error.
- **Presentation:** Boxes 1–5 are shown to the cent. Boxes 6–11B are shown to the nearest euro,
  rounding half up, with the exact amount and the rounding kept beside each.
- **Checks** (exceptions when they fail):
  - 3 = 1 + 2, and 5 = 3 − 4;
  - 6 ≥ 8A + 8B + 9 + 10 + 11B, and 7 ≥ 11A + 11B. The message says a credit note or a correction
    can explain a shortfall.
  - Line checks:
    - a tax point outside the period;
    - EU trade without a country and VAT number, or with a party in Cyprus or outside the EU;
    - a non-EU reverse charge with an EU supplier;
    - a domestic reverse charge with a foreign party.
- **The entry's party:** a line without its own customer or supplier takes the one on its
  entry's receivable or payable line, with its invoice number. This is how the party's country
  and VAT number reach the net lines.
- **Lines are still selected by accounting date.** A tax point in another period is flagged, not
  moved between returns. Which return a line belongs to is the owner's decision, with an adjuster
  in V1-2d.
- Only Cyprus entities can prepare a report (the only box rules there are). The empty
  `cy_vat_report.json` placeholder is removed.
- Reports prepared before this change keep their frozen snapshot. The screen and exports say the
  boxes are missing and suggest regenerating the draft or starting a new version. A draft
  prepared earlier must be regenerated before sign-off, because the figures now include the
  return.

## Consequences
- The return the owner types into the portal is on the screen, in the PDF and in Excel. Each
  figure traces to its lines and rule.
- The box rules, and the box labels taken from the specification, stay
  `PENDING_PROFESSIONAL_VERIFICATION` (#93). The labels are shown in English in both languages,
  so no official Greek wording is invented.
- Still to come:
  - the four-step workflow, adjustments and inclusion history (V1-2d);
  - schedules and reconciliation (V1-2e);
  - imports (V1-2f);
  - VIES (V1-2g).
