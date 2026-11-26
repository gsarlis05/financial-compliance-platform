# Real books readiness report

Status: **complete** (2026-11-26). It awaits your review. Brief:
[planning doc 26](planning/26-real-books-readiness-brief.md), approved 2026-11-26.

**Nothing was created on AWS, and no migration was applied anywhere but local development and CI.
Every file used is synthetic.** The bank and accounting-package presets are **to be confirmed**
until checked against your anonymised exports. The projection engine stays pending professional
review (#153), and the VAT rules stay pending verification (#93).

## What you can do now
- **Import bank statements from your four banks** without setting columns by hand (R-1, PR #249):
  - the file's encoding (including Windows Greek), separator, header, columns (English or Greek),
    decimal separator and date format are read from the file;
  - a question appears only where the file leaves something open;
  - you see a preview, and the layout is saved for the account.
- **Bring your books in** from spreadsheets (R-2, PR #250):
  - templates for the chart, customers and suppliers, the opening trial balance and the open
    invoices;
  - every problem is listed by row before anything is created;
  - accounts the chart lacks are mapped to chart accounts;
  - the opening balances become one balanced draft entry, with a line per open invoice.
- **From your accountant or your software** (R-3, PR #251):
  - a year-end trial balance as delivered: headings, subtotals, the file's total checked, Dr and
    Cr, the year's result carried into retained earnings;
  - aged receivables and payables reports, with missing customers and suppliers created on
    request;
  - day- or month-first dates;
  - Xero and QuickBooks presets.
- **The prior year by month** for comparisons (R-4, PR #252):
  - a monthly trial balance kept as comparatives, never as entries;
  - budget variance against the prior year, KPIs and statements read it;
  - each month must balance and agree with the opening balances.
- **A guide and examples** (R-5): [Moving your books in](user-guide/moving-your-books-in.md), and
  synthetic example files for every step and every bank preset in
  [`examples/books/`](../examples/books/).

## Acceptance
- **AC-R1.** Each preset's example statement is recognised and imported with no question asked. So
  is a file with Greek headers after account details. A file whose dates fit both orders asks one
  question. Tests: `tests/banking/test_detect.py` and `tests/onboarding/test_examples.py`.
- **AC-R2.** The full example set (chart, customers and suppliers, opening balances, open invoices
  and prior year) is imported through the API:
  - the opening entry is a draft, and nothing is in the trial balance until it is posted;
  - after posting, the trial balance equals the source file to the cent;
  - the accountant's trial balance with the package reports gives the same opening entry.
- **AC-R3.** A file is refused before anything is created, naming the row and the reason, when it:
  - does not balance;
  - repeats an invoice or lists one already booked;
  - names an unknown account or customer;
  - has a malformed or ambiguous amount, or a formula.

## Decisions taken in this work (ADRs)
- [ADR-0067](adr/0067-recognising-bank-csv-exports.md): bank CSVs are recognised from the file,
  and presets only break ties.
- [ADR-0068](adr/0068-importing-books-from-spreadsheets.md): imports are checked, then committed;
  the opening balances are one draft entry; set-up data is created directly.
- [ADR-0069](adr/0069-accountant-and-package-exports.md): accountants' and packages' files are
  read through the same reader, and package presets are to be confirmed.
- [ADR-0070](adr/0070-prior-year-comparatives.md): the prior year is kept as comparatives in the
  reporting gateway and never counted twice.

## What is needed from you
1. When convenient, send **anonymised exports**: one statement from each bank (CSV and, if offered,
   CAMT.053), and, if you use accounting software, a trial balance and an aged receivables report.
   These confirm the presets (#91, #92).
2. Then move your own books in, following the guide. **Use real data only on your own computer,
   never in the repository.**

## Known limitations
- The presets are to be confirmed (see above).
- Opening balances are in euro. A foreign-currency account's balance is entered as an entry in its
  currency.
- Comparatives have no daily or dimension detail, so the cash forecast's daily history starts with
  the books.
- Month names in dates are read in English.
