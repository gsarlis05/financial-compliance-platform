# Cyprus VAT return: coverage matrix

This page lists what the VAT return covers, where each rule comes from, which tests prove it, and
what is not covered. It reflects the box rules `CY-VAT-BOXES@1`
(`backend/src/fcp/modules/tax/data/cy_vat_boxes_v1.json`), status
**PENDING_PROFESSIONAL_VERIFICATION** (#93).

`tests/tax/test_vat_boxes.py` checks that this page lists every category and line kind exactly
as the rules do.

**Sources**
- **spec:** the owner's specification "Cyprus VAT Report Generator" v1.0, 23 November 2026
  (brief 25), §1 return summary and §2 transaction mapping.
- **[1]** Cyprus Tax Department, *VAT Guide: Fill in your VAT Return* (English, 6 August 2024).
- **[2]** Cyprus Tax Department, Greek completion guide for the VAT return (18 December 2019).

The official guides could not be read from the development environment, so every rule cites
the specification. Each rule is to be checked against [1] and [2] by a Cyprus tax professional.

## Supported

| Category | Output VAT | Input VAT | Net sale | Net purchase | Tests |
|---|---|---|---|---|---|
| DOMESTIC | 1 | 4 | 6 | 7 | `test_vat_return.py` local sale and purchase, credit note; golden quarter |
| ZERO_RATED | not in a box | not in a box | 6, 9 | not in a box | `test_vat_return.py` outputs |
| OUTSIDE_SCOPE_DEDUCTIBLE | not in a box | not in a box | 6, 10 | not in a box | `test_vat_return.py` outputs |
| EU_GOODS_SUPPLY | not in a box | not in a box | 6, 8A | not in a box | `test_vat_return.py` outputs |
| EU_SERVICES_SUPPLY | not in a box | not in a box | 6, 8B | not in a box | `test_vat_return.py` outputs |
| EU_GOODS_ACQUISITION | 2 | 4 | not in a box | 7, 11A | `test_vat_return.py` EU goods; `test_vat_return_api.py` |
| RC_EU_SERVICES | 1 | 4 | not in a box | 6, 7, 11B | `test_vat_return.py` EU service, 50% recovery; `test_vat_return_api.py` |
| RC_NON_EU_SERVICES | 1 | 4 | not in a box | 6, 7 | `test_vat_return.py` non-EU service |
| RC_DOMESTIC | 1 | 4 | not in a box | 6, 7 | `test_vat_return.py` party checks |
| IMPORT | not in a box | 4 | not in a box | not in a box | `test_vat_return.py` import VAT |

"Not in a box" means the line is listed under **Checks** as unsupported and feeds no box. The
specification does not map that kind of line for that category.

## Excluded (correctly left out of the return)

| Category | Why |
|---|---|
| NON_SUPPLY | Not a supply: payroll, financing and other non-supplies (spec §2). |
| SETTLEMENT | VAT payments, refunds and the settlement entry: in the reconciliation, not the return. |

## Not supported (shown as exceptions, never guessed)

| Case | What to do |
|---|---|
| EXEMPT supplies and purchases | Ask your tax adviser; record any amount as an adjustment. |
| The value of imports (IMPORT, net purchase) | Ask your tax adviser; import VAT itself goes to Box 4. |
| LEGACY_REVERSE_CHARGE (the old code RC) | Use a specific reverse-charge or acquisition code. |
| Special schemes (margin, travel agents, flat rate) | Not modelled; never treated as zero-rated. |
| Triangular transactions | Recorded on VIES statements, kept apart and compared with no box; ask your adviser. |
| Foreign-currency invoices | Waiting on the owner's decision (#219). |
| The Tax Department's XML format | Waiting for the official XSD (#220). |
| Bad-debt relief, capital goods and partial exemption | Enter them as adjustments with evidence. |

## Checks

| Check | Tests |
|---|---|
| Box 3 = 1 + 2, Box 5 = 3 − 4 | `test_vat_return.py` |
| Box 6 ≥ 8A + 8B + 9 + 10 + 11B, Box 7 ≥ 11A + 11B | `test_vat_return.py` value checks |
| VAT at the code's rate, net of non-recoverable VAT | `test_vat_compute.py`, `test_vat_return.py` |
| Tax point outside the period | `test_vat_return.py`, `test_vat_return_api.py` |
| EU party data: country, VAT number, member state | `test_vat_return.py` party checks |
| The ledger's VAT accounts reconcile to the return | `test_vat_return_api.py` schedules and reconciliation |
| A line in one return only | `test_vat_workflow.py` inclusions |
| Import VAT has its customs record; VAT and value agree; a declaration claimed once | `test_vat_imports.py` |
| Boxes 8A and 8B against the VIES statements, per partner and in total | `test_vat_vies.py` |
