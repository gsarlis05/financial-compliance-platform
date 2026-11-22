# ADR-0056: VAT period reports from the ledger; the law's items as sourced data; never filed
Status: **Accepted** (V1-2, #208; owner decision 2026-11-22, brief 24) · Date: 2026-11-22

## Context
The owner files the VAT return on the Tax Department's portal. They asked the platform to
produce, at the end of each VAT period, a report with what the law requires. VAT periods differ
between companies, and a company's periods can change.

The rules forbid inventing regulations, require tax rules to be versioned data, and forbid
filing returns. The official sources (the Cyprus VAT law, the VAT return form and its notes,
Directive 2006/112/EC) could not be read by the developer: the Tax Department's site, CyLaw and
EUR-Lex all answer automated access with a challenge. The owner has been asked for the
documents.

## Decision
- **Periods per entity as versioned schemes** (`tax_vat_period_scheme`). Each scheme is a
  length (1, 2, 3, 4, 6 or 12 months) and the first day of a period.
  - A change is a new scheme, starting where a period of the current scheme would start, so no
    period is ever cut in two.
  - A change cannot start before the end of a signed-off report's period.
  - Schemes are never edited or deleted (trigger).
- **The report is computed from posted lines only** (`ledger.api.vat_lines`), closing entries
  excluded:
  - **VAT** comes from lines on VAT accounts, by VAT code: output VAT counted credit-positive,
    input VAT debit-positive.
  - **Taxable amounts** come from lines on other accounts that carry a VAT code. Such a line
    counts as a sale or a purchase from the VAT on the same code in its entry. If that VAT does
    not settle it (none, as for zero-rated or exempt supplies, or both sides, as for a reverse
    charge), the account type decides.
  - **Settlement-code lines** (payments, refunds, the settlement entry) are shown separately.
  - **Checks:**
    - VAT at each code's rate against the VAT recorded, allowing one cent per entry;
    - VAT on a code that carries none;
    - VAT without a taxable amount;
    - a taxable amount without its VAT.
  - Every figure links to its lines.
- **Frozen snapshot and lifecycle.**
  - A draft can be regenerated.
  - Sign-off is refused before the period has ended, or while the period's figures differ from
    the snapshot.
  - The signer is not the preparer, except in a one-person workspace (ADR-0055), where it is
    recorded as self-approved.
  - "Filed" records the date and the portal's reference, entered by the owner. Nothing is sent
    anywhere.
  - A correction is a new version; signing it off supersedes the earlier one.
  - All of this is enforced by triggers.
- **The law's items are data** (`tax/data/cy_vat_report.json`). The file is empty, status
  `AWAITING_SOURCES`, until the official documents are supplied. It will then list each item
  with its source, marked `PENDING_PROFESSIONAL_VERIFICATION` (#93). Every report says so, on
  screen and in its exports. The VAT codes also show their unverified state.
- **Settlement entry:** a *draft* journal entry dated the period's last day. It moves the input
  VAT into the output VAT account with the settlement code, leaving the net amount payable or
  refundable there. It follows the normal approval and posting workflow.
- **Due date:** entered by the owner. It is not computed, because the deadline rules come from
  the sources still awaited.

## Consequences
- The owner gets a complete, traceable VAT analysis for every period now. The law's own layout
  is added without changing the code, as data, once the documents arrive.
- The analysis is only as good as the VAT coding of entries. The checks point out entries that
  look wrong; they do not correct them.
- EU cross-border cases (intra-Community supplies and acquisitions, services) need their own VAT
  codes from the sources. They are not added before then.
