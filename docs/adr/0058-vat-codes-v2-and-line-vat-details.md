# ADR-0058: VAT code categories, box rules as data, and VAT details on each line
Status: **Accepted** (V1-2b, #213; owner decisions 2026-11-23, brief 25) · Date: 2026-11-23

## Context
The owner chose to build everything in their specification "Cyprus VAT Report Generator" now
(brief 25), with its box rules used but marked unverified. The 13-box return (V1-2c) needs to
know, for each line, which boxes it feeds. The VAT codes of M2-3 said only the rate and a
treatment, so a reverse charge on EU services could not be told from one on domestic supplies,
and a line could not say how much of its input VAT is recoverable or when its tax point was.

The official sources still cannot be read from the development environment (they answer
automated access with a challenge). Every rule therefore cites the specification and the Tax
Department's two completion guides by title and address, and stays
`PENDING_PROFESSIONAL_VERIFICATION` (#93).

## Decision
- **Each VAT code has a category** (`ledger_vat_code.category`), one of 14:
  `DOMESTIC`, `ZERO_RATED`, `EXEMPT`, `OUTSIDE_SCOPE_DEDUCTIBLE`, `EU_GOODS_SUPPLY`,
  `EU_SERVICES_SUPPLY`, `EU_GOODS_ACQUISITION`, `RC_EU_SERVICES`, `RC_NON_EU_SERVICES`,
  `RC_DOMESTIC`, `IMPORT`, `LEGACY_REVERSE_CHARGE`, `NON_SUPPLY`, `SETTLEMENT`.
  - The catalogue (`ledger/vat/cy.json`) grows from 8 to 32 codes: the 3% rate, and the
    acquisition, reverse-charge and import codes at 19%, 9%, 5% and 3%.
  - Existing codes keep their ids, so posted lines are untouched. The old `RC` code becomes
    `LEGACY_REVERSE_CHARGE`: it does not say which reverse charge applies.
- **The box rules are versioned data** (`tax/data/cy_vat_boxes_v1.json`, `CY-VAT-BOXES@1`),
  read by `tax.boxes`:
  - the 13 boxes with their labels, and the two formulas (3 = 1 + 2, 5 = 3 − 4);
  - for each category and line kind (`OUTPUT_VAT`, `INPUT_VAT`, `NET_SALE`, `NET_PURCHASE`)
    the boxes it feeds, each with its source;
  - categories that are **excluded** (non-supplies, settlements), with the reason;
  - cases that are **unsupported** (exempt supplies, the value of imports, the old `RC` code),
    with the reason. An unsupported line will show as an exception in the report, never be
    guessed into a box.
  - A rule may never be added without a source. A test checks every category and line kind is
    mapped, excluded or unsupported, and that the matrix equals the specification's §2 table.
- **Each journal line can carry VAT details**, kept in the entry's content hash and mirrored by
  a reversal:
  - `tax_point`: the date of the tax point when it differs from the accounting date; it needs a
    VAT code;
  - on input VAT lines only, `vat_recovery_percent` (0–100) and `vat_blocked` (the VAT not
    recoverable, in cents, not negative). The line's amount is the recoverable VAT, and it must
    equal (recoverable + blocked) × recovery % within one cent. The database checks the ranges.
- **Each customer or supplier can carry a country** (ISO 3166-1 alpha-2, upper case, checked by
  the database), for the EU schedules and VIES checks (V1-2e, V1-2g).
- `ledger.api.vat_lines` returns, per line, the category, the tax point, the recovery details,
  the counterparty's country and VAT number and the entry's status, so the tax module never
  reads ledger tables.

## Consequences
- V1-2c can compute each box from line contributions, with the rule and its source for each.
- Exempt supplies and the value of imports wait for a tax professional's answer; until then the
  owner records them as manual adjustments (V1-2d).
- Foreign-currency invoices (#219) and the official XML format (#220) stay open for the owner.
- Nothing here files anything, and the rates and rules stay marked unverified.
