# 25 — Cyprus VAT Return Brief: the full return package (version 1, V1-2)

Status: **APPROVED (2026-11-23).** The owner supplied a functional specification, "Cyprus VAT
Report Generator", version 1.0, dated 23 November 2026, called *the specification* below. It is
not kept in the repository because it carries personal details. The owner answered three
questions on it:

| Question | Owner's answer |
|---|---|
| Scope for version 1 | **Everything in the specification now** |
| Workflow | **Four steps as in the specification:** Draft → Reviewed → Finalised → Filed |
| Source | **Use its box rules, marked unverified** (`PENDING_PROFESSIONAL_VERIFICATION`, #93) |

The specification is a summary that cites the Tax Department's official sources. It is not an
official document itself. The official documents could not be read by the developer (the Tax
Department's site refuses automated access), so every box rule cites both the specification and
the official source it names:
- **[1]** VAT Guide: Fill in your VAT Return (English, 6 August 2024),
  `https://www.gov.cy/media/sites/167/2026/01/ENG-Οδηγός-ΦΠΑ.pdf`.
- **[2]** Greek completion guide (18 December 2019), `www.mof.gov.cy/mof/tax/TaxDep.nsf/…` (its
  Box 5 sign convention and reverse-charge examples).
- **[3]** VAT returns and amendments: filing periods, electronic submission, XML and XSD:
  `https://www.gov.cy/mof-tax/documents/ypovoli-tropopoiisi-diloseon-f-p-a/`.
- **[4]** VAT rates: `https://www.gov.cy/mof-tax/documents/syntelestes-f-p-a/`.
- **[5]** VIES statement FAQs.
- **[6]** Amendments to normal-regime returns (Tax Department announcement).

**Unchanged rules:**
- The platform never files a return.
- A generated report or file does not prove a return was filed.
- Money is `Decimal`.
- Nothing is invented: a case the rules do not cover is shown as an exception.

## 1. The return (specification §1)
**The boxes:**
- **1** output VAT, including applicable reverse-charge VAT;
- **2** VAT on EU acquisitions of goods and related costs;
- **3** = 1 + 2;
- **4** deductible input VAT, including eligible import, acquisition and reverse-charge VAT;
- **5** = 3 − 4 (positive: payable; negative: credit);
- **6** sales and other reportable outputs, excluding VAT, including the relevant reverse-charge
  values;
- **7** purchases and other reportable inputs, excluding VAT;
- **8A** intra-Community supplies of goods;
- **8B** qualifying services supplied to other EU member states;
- **9** zero-rated outputs, excluding 8A and 8B;
- **10** qualifying outside-scope supplies with input deduction rights, excluding 8B;
- **11A** EU acquisitions of goods and related costs;
- **11B** services received from VAT-registered suppliers in other EU member states.

**Presentation:**
- Boxes 1–5 are shown to the cent; boxes 6–11B to the nearest euro, with the rounding difference
  shown.
- Unused boxes show zero.
- The report carries:
  - identification: legal name, company identifier, VAT number, tax identification number, EUR;
  - the period, its deadlines, the return version, status, preparer, reviewer and timestamps;
  - the filing reference and date, and the payment reference.

## 2. Mapping (specification §2)
Each line carries a VAT code. Each code maps, as versioned and effective-dated data, to the boxes
its VAT and its net value feed:

| Transaction | VAT boxes | Net-value boxes |
|---|---|---|
| Domestic taxable sale | 1 | 6 |
| Domestic deductible purchase | 4 | 7 |
| EU goods acquisition | 2; 4 if deductible | 7, 11A |
| EU services received (reverse charge) | 1; 4 if deductible | 6, 7, 11B |
| Non-EU services received (reverse charge) | 1; 4 if deductible | 6, 7 |
| Domestic reverse charge | 1; 4 if deductible | 6, 7 |
| EU goods supply | — | 6, 8A |
| EU B2B services supply | — | 6, 8B |
| Zero-rated local supply or export | 0 | 6, 9 |
| Outside-scope supply with deduction rights | — | 6, 10 |

**Rules for codes and lines:**
- Codes are separate for goods and services, sales and purchases, domestic, EU and non-EU,
  zero-rated, exempt and outside-scope, and each reverse-charge category.
- Rates are 19%, 9%, 5%, 3% and 0%, effective-dated. Temporary reliefs have start and end dates.
- Each line records:
  - the deductible share (recovery %) and any blocked VAT;
  - the tax point, kept apart from the posting date, with the period in which input VAT is
    claimed.
- Credit and debit notes, linked reversals, mixed-rate invoices, assets, imports and VAT journals
  are all supported.
- Non-supplies (payroll, financing) are excluded explicitly.
- Special schemes are never treated as zero-rated: they show as unsupported exceptions.

## 3. Schedules, line data and drill-down (specification §3)
**Schedules:**
- sales;
- purchases;
- EU trade (counterparty VAT number and country);
- reverse charge (overseas and domestic);
- imports (customs reference, date, taxable value, evidence, no duplicate claims);
- adjustments (credit notes, bad-debt relief, corrections, partial exemption, capital goods,
  each with reason and evidence);
- reconciliation;
- exceptions.

**Drill-down:**
- Each line shows its contribution to every box, why it maps there, and the rule version used.
- Every box opens its lines and subtotal.
- Lines can be filtered by date, party, country, VAT code, document type and account.

**Precision:**
- Decimal arithmetic throughout. Original amounts and EUR amounts are both kept, with the rate.
- Invoice, line and return rounding are kept distinct.
- Re-running an unchanged finalised return gives identical totals.

## 4. Checks, reconciliation and workflow (specification §4)
**Checks:**
- Box 3 = 1 + 2, and Box 5 = 3 − 4.
- Box 6 ≥ 8A + 8B + 9 + 10 + 11B, and Box 7 ≥ 11A + 11B, explaining exceptions caused by
  corrections or rounding.
- Code eligibility, effective dates, arithmetic and recovery limits. Box 2 is not forced to 19%
  of Box 11A.
- Duplicates, missing documents or codes, incomplete EU party data, future tax points, and
  postings outside the period.
- Boxes 8A and 8B against the VIES statements, with timing and rounding differences.

**Reconciliation:**
- Opening VAT control balances, the period's movements, adjustments, settlement transfers,
  payments and refunds, and closing balances.
- The return bridged to the ledger, with explicit reconciling items.
- Earlier credits, payments, interest and penalties kept apart from Box 5.

**Workflow:**
- **Draft → Reviewed → Finalised → Filed.** Filing needs the submission evidence. Preparer,
  reviewer and timestamps are recorded.
- In a one-person workspace (V1-1), the reviewer and finaliser may be the preparer, recorded as
  self-approved.
- **Manual adjustments** each carry an amount, the box affected, a reason, evidence and an
  approval. Original totals, adjustments and final totals are shown separately.
- **Finalising** stores an immutable snapshot: lines, rule versions, mappings, adjustments,
  exports. Later entries produce a visible difference list.
- **No line is reported twice.** Each line's inclusion is recorded per return; an intentional
  corrective inclusion is explained.
- Old errors are not pushed into the current return automatically: amendments follow the Cyprus
  procedure [6].

## 5. Outputs and acceptance (specification §5)
**Exports:**
- **PDF:** summary, schedules, reconciliation, exceptions, sign-off; numbered pages, with the
  company, period and version on each page.
- **Excel:** sheets Summary, Sales, Purchases, EU Trade, Reverse Charge, Imports, Adjustments,
  Reconciliation, Exceptions and Tax Code Mapping, with numeric cells and filters.
- **CSV:** UTF-8 lines with stable IDs, documented columns, every box contribution.
- **Tax Department XML (optional):** only against the official XSD and guide [3].

**Acceptance fixtures** (19% VAT and full recovery unless stated):

| Scenario | Expected boxes |
|---|---|
| Local sale, net 1,000 | Box 1 +190; Box 6 +1,000 |
| Local purchase, net 500 | Box 4 +95; Box 7 +500 |
| EU goods acquisition, net 1,000 | Box 2 +190; Box 4 +190; Boxes 7 and 11A +1,000 |
| EU service received, net 100 | Box 1 +19; Box 4 +19; Boxes 6, 7, 11B +100 |
| Non-EU service received, net 100 | Box 1 +19; Box 4 +19; Boxes 6, 7 +100 |
| EU service, net 100, recovery 50% | Box 1 +19; Box 4 +9.50; Boxes 6, 7, 11B +100 |
| Credit note on the local sale | Box 1 −190; Box 6 −1,000 |

The first five together give: Box 1 = 228, 2 = 190, 3 = 418, 4 = 323, 5 = 95 payable,
6 = 1,200, 7 = 1,700, 11A = 1,000, 11B = 100, and 8A, 8B, 9, 10 = 0.

Also tested: nil returns, mixed rates, partial exemption, imports, foreign currencies, rounding
boundaries, late entries, duplicates, amendments, period locking, and consistent totals across
exports.

A **coverage matrix** (`docs/vat/coverage.md`) lists the supported categories, their sources and
tests, and the unsupported cases.

## 6. Work, in order (one issue and one PR each)
| # | Item | Status |
|---|---|---|
| V1-2a | VAT periods per company; a period report from the ledger (by code, VAT accounts, checks, lines); sign-off, filing record, versions, settlement draft; PDF/Excel | Built (#208, PR #221) |
| V1-2b | VAT code catalogue v2 (categories, rates incl. 3%, effective dates, box mapping as versioned rule data) and line tax data (tax point, recovery %, blocked VAT; counterparty country and VAT number) | Done, PR #223 (#213) |
| V1-2c | The 13-box return from line contributions; rounding; cross-field checks; drill-down per box with reason and rule version; acceptance fixtures | Done, PR #224 (#214) |
| V1-2d | Workflow Draft → Reviewed → Finalised → Filed; manual adjustments with approval; inclusion history (no double reporting); late-entry difference list; amendments | #215 |
| V1-2e | Schedules, reconciliation with opening and closing balances, exceptions; PDF, Excel (named sheets), CSV; coverage matrix | #216 |
| V1-2f | Imports: customs reference, date and value, import VAT evidence, no duplicate claims | #217 |
| V1-2g | VIES: the owner records each VIES statement; reconciliation to Boxes 8A and 8B | #218 |
| V1-2h | Foreign currency on VAT lines | **Owner decision needed** (conflicts with D8; #219) |
| V1-2i | Tax Department XML export | **Needs the official XSD and guide** from the owner (#220) |
