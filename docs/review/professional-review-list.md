# Professional review list

Everything below is used by the platform and has **not yet been confirmed by a qualified Cyprus tax professional** (#93). Tick each item when it is confirmed, or write the correction and its source next to it, and send the list back: corrections become new versions of the data.

This file is generated from the platform's data (`python -m fcp.devtools.review_list`); do not edit it by hand.

## 1. VAT codes and rates

Source note in the data: *Seeded from widely published Cyprus VAT rates and, for the categories, the owner's VAT specification of 2026-11-23 (brief 25). Every entry is UNVERIFIED until a qualified Cyprus tax professional confirms it (owner decision #93). Validity windows are open-ended until verified dates are supplied.*

| ✓ | Code | Name | Greek name | Category | Treatment | Rate |
|---|---|---|---|---|---|---|
| ☐ | S19 | Standard rate 19% | Κανονικός συντελεστής 19% | DOMESTIC | STANDARD | 19% |
| ☐ | R9 | Reduced rate 9% | Μειωμένος συντελεστής 9% | DOMESTIC | REDUCED | 9% |
| ☐ | R5 | Reduced rate 5% | Μειωμένος συντελεστής 5% | DOMESTIC | REDUCED | 5% |
| ☐ | Z0 | Zero rate | Μηδενικός συντελεστής | ZERO_RATED | ZERO | 0% |
| ☐ | EX | Exempt | Απαλλασσόμενη | EXEMPT | EXEMPT | no rate |
| ☐ | RC | EU reverse charge (old code: choose a specific reverse-charge or acquisition code) | Αντίστροφη επιβάρυνση ΕΕ (παλαιός κωδικός: επιλέξτε συγκεκριμένο κωδικό) | LEGACY_REVERSE_CHARGE | REVERSE_CHARGE | 19% |
| ☐ | OUT | Outside the scope of VAT: not a supply (payroll, financing) | Εκτός πεδίου ΦΠΑ: όχι παράδοση (μισθοδοσία, χρηματοδότηση) | NON_SUPPLY | OUT_OF_SCOPE | no rate |
| ☐ | SETTLE | VAT settlement (payment or refund) | Εκκαθάριση ΦΠΑ (πληρωμή ή επιστροφή) | SETTLEMENT | SETTLEMENT | no rate |
| ☐ | R3 | Reduced rate 3% | Μειωμένος συντελεστής 3% | DOMESTIC | REDUCED | 3% |
| ☐ | OSD | Outside scope, with the right to deduct input VAT | Εκτός πεδίου, με δικαίωμα έκπτωσης ΦΠΑ εισροών | OUTSIDE_SCOPE_DEDUCTIBLE | OUT_OF_SCOPE | no rate |
| ☐ | EUGS | Intra-Community supply of goods | Ενδοκοινοτική παράδοση αγαθών | EU_GOODS_SUPPLY | ZERO | 0% |
| ☐ | EUSS | Services supplied to a business in another EU state | Υπηρεσίες σε επιχείρηση άλλου κράτους μέλους ΕΕ | EU_SERVICES_SUPPLY | OUT_OF_SCOPE | no rate |
| ☐ | EUGA19 | Intra-Community acquisition of goods at 19% | Ενδοκοινοτική απόκτηση αγαθών με 19% | EU_GOODS_ACQUISITION | REVERSE_CHARGE | 19% |
| ☐ | RCEU19 | Services received from another EU state (reverse charge) at 19% | Υπηρεσίες από άλλο κράτος μέλος ΕΕ (αντίστροφη επιβάρυνση) με 19% | RC_EU_SERVICES | REVERSE_CHARGE | 19% |
| ☐ | RCNEU19 | Services received from outside the EU (reverse charge) at 19% | Υπηρεσίες εκτός ΕΕ (αντίστροφη επιβάρυνση) με 19% | RC_NON_EU_SERVICES | REVERSE_CHARGE | 19% |
| ☐ | RCDOM19 | Domestic reverse charge at 19% | Εγχώρια αντίστροφη επιβάρυνση με 19% | RC_DOMESTIC | REVERSE_CHARGE | 19% |
| ☐ | IMP19 | Import VAT paid at customs at 19% | ΦΠΑ εισαγωγής στο τελωνείο με 19% | IMPORT | STANDARD | 19% |
| ☐ | EUGA9 | Intra-Community acquisition of goods at 9% | Ενδοκοινοτική απόκτηση αγαθών με 9% | EU_GOODS_ACQUISITION | REVERSE_CHARGE | 9% |
| ☐ | RCEU9 | Services received from another EU state (reverse charge) at 9% | Υπηρεσίες από άλλο κράτος μέλος ΕΕ (αντίστροφη επιβάρυνση) με 9% | RC_EU_SERVICES | REVERSE_CHARGE | 9% |
| ☐ | RCNEU9 | Services received from outside the EU (reverse charge) at 9% | Υπηρεσίες εκτός ΕΕ (αντίστροφη επιβάρυνση) με 9% | RC_NON_EU_SERVICES | REVERSE_CHARGE | 9% |
| ☐ | RCDOM9 | Domestic reverse charge at 9% | Εγχώρια αντίστροφη επιβάρυνση με 9% | RC_DOMESTIC | REVERSE_CHARGE | 9% |
| ☐ | IMP9 | Import VAT paid at customs at 9% | ΦΠΑ εισαγωγής στο τελωνείο με 9% | IMPORT | REDUCED | 9% |
| ☐ | EUGA5 | Intra-Community acquisition of goods at 5% | Ενδοκοινοτική απόκτηση αγαθών με 5% | EU_GOODS_ACQUISITION | REVERSE_CHARGE | 5% |
| ☐ | RCEU5 | Services received from another EU state (reverse charge) at 5% | Υπηρεσίες από άλλο κράτος μέλος ΕΕ (αντίστροφη επιβάρυνση) με 5% | RC_EU_SERVICES | REVERSE_CHARGE | 5% |
| ☐ | RCNEU5 | Services received from outside the EU (reverse charge) at 5% | Υπηρεσίες εκτός ΕΕ (αντίστροφη επιβάρυνση) με 5% | RC_NON_EU_SERVICES | REVERSE_CHARGE | 5% |
| ☐ | RCDOM5 | Domestic reverse charge at 5% | Εγχώρια αντίστροφη επιβάρυνση με 5% | RC_DOMESTIC | REVERSE_CHARGE | 5% |
| ☐ | IMP5 | Import VAT paid at customs at 5% | ΦΠΑ εισαγωγής στο τελωνείο με 5% | IMPORT | REDUCED | 5% |
| ☐ | EUGA3 | Intra-Community acquisition of goods at 3% | Ενδοκοινοτική απόκτηση αγαθών με 3% | EU_GOODS_ACQUISITION | REVERSE_CHARGE | 3% |
| ☐ | RCEU3 | Services received from another EU state (reverse charge) at 3% | Υπηρεσίες από άλλο κράτος μέλος ΕΕ (αντίστροφη επιβάρυνση) με 3% | RC_EU_SERVICES | REVERSE_CHARGE | 3% |
| ☐ | RCNEU3 | Services received from outside the EU (reverse charge) at 3% | Υπηρεσίες εκτός ΕΕ (αντίστροφη επιβάρυνση) με 3% | RC_NON_EU_SERVICES | REVERSE_CHARGE | 3% |
| ☐ | RCDOM3 | Domestic reverse charge at 3% | Εγχώρια αντίστροφη επιβάρυνση με 3% | RC_DOMESTIC | REVERSE_CHARGE | 3% |
| ☐ | IMP3 | Import VAT paid at customs at 3% | ΦΠΑ εισαγωγής στο τελωνείο με 3% | IMPORT | REDUCED | 3% |

For each code, check:
- the rate, and the date from which it applies (all are open-ended today);
- that the category says what the transaction is (it decides the return's boxes);
- that no code is missing, for example for temporary reliefs.

## 2. The VAT return's boxes

Rules `CY-VAT-BOXES@1`, status **PENDING_PROFESSIONAL_VERIFICATION**. Sources:

- Owner's specification 'Cyprus VAT Report Generator' v1.0, 2026-11-23 (brief 25)
- Cyprus Tax Department - VAT Guide: Fill in your VAT Return (English, 6 August 2024) (https://www.gov.cy/media/sites/167/2026/01/ENG-%CE%9F%CE%B4%CE%B7%CE%B3%CF%8C%CF%82-%CE%A6%CE%A0%CE%91.pdf)
- Cyprus Tax Department - Greek completion guide for the VAT return (18 December 2019) (https://www.mof.gov.cy/mof/tax/TaxDep.nsf/F4C32AE3D3F79397C22589CF002832E6/$file/%CE%9F%CE%B4%CE%B7%CE%B3%CF%8C%CF%82%20%CE%B3%CE%B9%CE%B1%20%CE%A3%CF%85%CE%BC%CF%80%CE%BB%CE%AE%CF%81%CF%89%CF%83%CE%B7%20%CE%94%CE%AE%CE%BB%CF%89%CF%83%CE%B7%CF%82%20%CE%A6%CE%A0%CE%91%2018_12_2019.pdf)

### 2.1 Box labels

| ✓ | Box | Label used | Kind |
|---|---|---|---|
| ☐ | 1 | Output VAT, including applicable reverse-charge VAT | VAT |
| ☐ | 2 | VAT on EU acquisitions of goods and related costs | VAT |
| ☐ | 3 | Total VAT due (Box 1 + Box 2) | VAT |
| ☐ | 4 | Deductible input VAT, including eligible import, acquisition and reverse-charge VAT | VAT |
| ☐ | 5 | Net VAT (Box 3 - Box 4): positive is payable, negative is a credit | VAT |
| ☐ | 6 | Sales and other reportable outputs, excluding VAT, including relevant reverse-charge values | VALUE |
| ☐ | 7 | Purchases and other reportable inputs, excluding VAT | VALUE |
| ☐ | 8A | Intra-Community supplies of goods | VALUE |
| ☐ | 8B | Qualifying services supplied to other EU member states | VALUE |
| ☐ | 9 | Zero-rated outputs, excluding Boxes 8A and 8B | VALUE |
| ☐ | 10 | Qualifying outside-scope supplies with input deduction rights, excluding Box 8B | VALUE |
| ☐ | 11A | EU acquisitions of goods and related costs | VALUE |
| ☐ | 11B | Services received from VAT-registered suppliers in other EU member states | VALUE |

Labels are shown in English in both languages. Please give the official Greek wording if it should be shown.

### 2.2 Which boxes each kind of line feeds

| ✓ | Category | Line | Boxes | Source |
|---|---|---|---|---|
| ☐ | DOMESTIC | OUTPUT_VAT | 1 | spec §2: domestic taxable sale |
| ☐ | DOMESTIC | NET_SALE | 6 | spec §2: domestic taxable sale |
| ☐ | DOMESTIC | INPUT_VAT | 4 | spec §2: domestic deductible purchase |
| ☐ | DOMESTIC | NET_PURCHASE | 7 | spec §2: domestic deductible purchase |
| ☐ | EU_GOODS_ACQUISITION | OUTPUT_VAT | 2 | spec §2: qualifying EU goods acquisition |
| ☐ | EU_GOODS_ACQUISITION | INPUT_VAT | 4 | spec §2: qualifying EU goods acquisition (4 if deductible) |
| ☐ | EU_GOODS_ACQUISITION | NET_PURCHASE | 7, 11A | spec §2: qualifying EU goods acquisition |
| ☐ | RC_EU_SERVICES | OUTPUT_VAT | 1 | spec §2: EU services received, Cyprus reverse charge |
| ☐ | RC_EU_SERVICES | INPUT_VAT | 4 | spec §2: EU services received (4 if deductible) |
| ☐ | RC_EU_SERVICES | NET_PURCHASE | 6, 7, 11B | spec §2: EU services received |
| ☐ | RC_NON_EU_SERVICES | OUTPUT_VAT | 1 | spec §2: non-EU services received, Cyprus reverse charge |
| ☐ | RC_NON_EU_SERVICES | INPUT_VAT | 4 | spec §2: non-EU services received (4 if deductible) |
| ☐ | RC_NON_EU_SERVICES | NET_PURCHASE | 6, 7 | spec §2: non-EU services received |
| ☐ | RC_DOMESTIC | OUTPUT_VAT | 1 | spec §2: domestic reverse-charge receipt |
| ☐ | RC_DOMESTIC | INPUT_VAT | 4 | spec §2: domestic reverse-charge receipt (4 if deductible) |
| ☐ | RC_DOMESTIC | NET_PURCHASE | 6, 7 | spec §2: domestic reverse-charge receipt |
| ☐ | EU_GOODS_SUPPLY | NET_SALE | 6, 8A | spec §2: qualifying EU goods supply |
| ☐ | EU_SERVICES_SUPPLY | NET_SALE | 6, 8B | spec §2: qualifying EU B2B service supply |
| ☐ | ZERO_RATED | NET_SALE | 6, 9 | spec §2: qualifying zero-rated local supply or export |
| ☐ | OUTSIDE_SCOPE_DEDUCTIBLE | NET_SALE | 6, 10 | spec §2: qualifying outside-scope supply with deduction rights |
| ☐ | IMPORT | INPUT_VAT | 4 | spec §1: Box 4 includes eligible import VAT |

### 2.3 Left out of the return

| ✓ | Category | Why |
|---|---|---|
| ☐ | NON_SUPPLY | Not a supply (payroll, financing and other non-supplies are excluded explicitly; spec §2). |
| ☐ | SETTLEMENT | A VAT payment, refund or settlement transfer: part of the reconciliation, not of the return. |

### 2.4 Not covered: shown as exceptions, never guessed

| ✓ | Case | What the platform says | Question for you |
|---|---|---|---|
| ☐ | EXEMPT | Exempt supplies and purchases are not mapped by the specification. Check with your tax adviser and record any amount as a manual adjustment. | Should exempt supplies and purchases appear in Box 6 or Box 7? |
| ☐ | IMPORT (NET_PURCHASE) | The value of imports is not mapped by the specification. Check with your tax adviser. | Should the value of imports appear in Box 7? |
| ☐ | LEGACY_REVERSE_CHARGE | The old code RC does not say which reverse charge applies. Use a specific reverse-charge or acquisition code. | None: the old code is replaced by specific codes. |

## 3. How the platform prepares the return

| ✓ | Topic | What the platform does |
|---|---|---|
| ☐ | Rounding | Boxes 1 to 5 to the cent; Boxes 6 to 11B to the nearest euro, half up, with the rounding shown (ADR-0059). |
| ☐ | Which return a line belongs to | Lines are chosen by their accounting date. A tax point in another period is flagged, not moved (ADR-0059). |
| ☐ | Partial recovery | Box 4 takes only the recoverable input VAT; the non-recoverable part is kept on the line and in no box (ADR-0058, ADR-0059). |
| ☐ | Reverse charge | The VAT goes to Box 1 (EU acquisitions of goods: Box 2) and, as far as it is recoverable, Box 4; the net value to Boxes 6 and 7, and 11B for EU services. |
| ☐ | Credit notes | A credit note or reversal reduces every box its original fed. |
| ☐ | Checks | Box 6 ≥ 8A + 8B + 9 + 10 + 11B and Box 7 ≥ 11A + 11B; a shortfall is reported, with the note that a credit note can explain it. |
| ☐ | EU member states | The 27 member states, GR for Greece (EL in VAT numbers), used to check EU trade partners. |
| ☐ | Imports | Import VAT in Box 4 needs the customs declaration recorded; its taxable value at the code's rate must give that VAT (ADR-0062). |
| ☐ | VIES | Partners matched on country and VAT number without the prefix; triangular amounts kept apart and compared with no box: how should they be reported? (ADR-0063) |
| ☐ | Corrections of a filed return | A new version is prepared and compared with the filed one; the procedure for filing a correction is not described by the platform (ADR-0060). |
| ☐ | Adjustments | Manual adjustments change one box with a reason and evidence, approved by a second person except in a one-person workspace (ADR-0060). |
| ☐ | Foreign currency | Amounts are converted into euros at the exchange rate of the transaction's date and time, with its source (your decision). Does the VAT law require a particular rate for VAT, for example a published rate on the tax point? |
| ☐ | Exchange differences | Foreign balances are revalued at the closing rate and settled differences recognised, both in profit or loss (ADR-0066); no tax adjustment is made. How are realised and unrealised exchange differences treated for income tax? |

## 4. Corporate income tax (projections only)

Source note in the data: *Seeded from published professional summaries of Cyprus corporate income tax (owner decision D4, 2026-11-15). The primary texts (Income Tax Law and the reform laws published in the Official Gazette on 31 December 2025) could not be opened from the development environment. Every rule set is UNVERIFIED until a qualified Cyprus tax professional confirms it (owner item #154). Years before 2020 are not seeded.*

### CY:CIT:2020: 2020-01-01 to 2025-12-31

- ☐ Rate: 12.5%
- ☐ Losses carried forward: 5 years
- ☐ Provisional tax instalments: 31/7 (50%), 31/12 (50%)
- ☐ Final payment: 1/8 of the following year
- Note: Rate 12.5% and five-year loss carry-forward as in force before the 2026 reform; to be confirmed with the effective dates (#154).

### CY:CIT:2026: 2026-01-01 to open

- ☐ Rate: 15%
- ☐ Losses carried forward: 7 years
- ☐ Provisional tax instalments: 31/7 (50%), 31/12 (50%)
- ☐ Final payment: 1/8 of the following year
- Note: 15% from tax year 2026; seven-year carry-forward from 2026 (s.13(1) first proviso, 'five' replaced by 'seven'). Not yet confirmed: how the seven years apply to losses of years before 2026 (modelled here only for losses arising from 2026), and the amending law's number (summaries cite 207(I)/2025 and 244(I)/2025). See #154.

## 5. Capital allowances

The allowance classes and rates are entered by you for each company (Fixed assets, Allowance
classes), each with its source. Please have the classes you entered checked.

## 6. The projection engine

The validation package is in `docs/validation/`. Its reviewer sign-off form,
`docs/validation/05-reviewer-sign-off.md`, is for an independent qualified accountant (ACA, ACCA,
CPA or equivalent) to complete. Until then, projections are marked
**PENDING_PROFESSIONAL_REVIEW**.

## 7. Already decided by you (no review needed)

- A VIES correction carries the month's full figures (23 November 2026).
- Foreign-currency purchases are converted to euros at the exchange rate of the date and time of
  the purchase (23 November 2026; being built, #219).
- The Tax Department's XML file is left for later (23 November 2026; reminder in #220).
