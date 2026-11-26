# ADR-0068: Importing existing books from spreadsheets
Status: **Accepted** (R-2, #245; brief 26) · Date: 2026-11-26

## Context
To move to real books, the owner must bring in:
- the chart of accounts;
- the customers and suppliers;
- the opening balances, with the invoices still open behind the receivables and payables.

These arrive as spreadsheets: the templates provided, or the owner's or the accountant's own
files.

The rules that apply:
- nothing is posted by an import;
- every file is checked before anything is created;
- money is exact;
- the books always balance.

## Decision
- **A new module, `onboarding`**, that only uses other modules' public interfaces:
  - `ledger.add_account` and `create_entry_draft`;
  - `registers.add_counterparty`.

  It has no tables of its own.
- **Templates are data.** `onboarding/templates.json` holds four templates:
  - chart of accounts;
  - customers and suppliers;
  - opening trial balance;
  - open invoices.

  For each it gives the columns, the header names recognised (English and Greek), the notes and a
  synthetic example. Each template downloads as .xlsx or CSV. In the .xlsx, the first sheet is the
  only one read back; a second sheet, "How to fill in", explains each column.
- **Columns are found by their header names**, compared without case, accents or punctuation.
  The header can be anywhere in the first 10 rows, so a file with a title row works. Columns may
  come in any order, and extra columns are ignored.
- **Reading is hardened** in the same way as the budget workbook (threat T9):
  - at most 5 MB;
  - an .xlsx must be a zip with no macros and no more than 200 parts or 50 MB unpacked;
  - formulas are refused;
  - text starting with `= + - @`, a tab or a line break is refused;
  - at most 5,000 rows are read.
- **Amounts are exact, and are refused when ambiguous.**
  - Accepted: `1250.00`, `1.250,00`, `1,250.50`, `-4,20` and `(300.00)`.
  - Excel numbers are read through `Decimal(repr(...))`.
  - A value such as `1,250` or `1.250` could mean either thousands or decimals. It is refused
    with a message saying how to write it, never guessed.
  - Typed dates are read day first, the Cyprus convention.
- **Check, then import.** Every import is a single call with `commit=false|true`:
  - It first checks every row and lists every problem by file, row and column.
  - With no problems, it runs the real services inside a transaction.
  - A check (`commit=false`) always rolls that transaction back. So the check also applies the
    services' own rules, and it shows exactly what would be created.
  - A commit with any problem creates nothing.
- **Set-up data is created directly.** Accounts and customers or suppliers already present and
  identical are skipped; if they differ, that is a problem. Headings are created before the
  accounts under them, and a loop of parents is refused.
- **Opening balances become one draft entry** (source IMPORT), dated on the opening date.
  - It has one line per account of the trial balance.
  - For a receivables or payables account, there is one line per open invoice instead, carrying
    the customer or supplier, the invoice number and the due date. The due date defaults to the
    invoice date plus the payment terms. The invoices must add up to the account's balance in
    the trial balance, so those lines become the open items (AC-M2-2) and the ledger still
    agrees with the source.
  - The entry must balance; otherwise the difference is shown.
  - A VAT account's balance carries the `SETTLE:open` code, as the VAT settlement does, so it
    belongs to no VAT return.
  - A second opening import is refused while an earlier one is not void.
  - An invoice already in the books is refused.
  - A fiscal year must contain the opening date.
- **Accounts the chart lacks are mapped**, not created on the fly. The check lists each unknown
  code with its name from the file, and the screen offers the chart's accounts. Several old
  accounts may map to one, and their balances are then added together.
- **Audited.** A completed import records the kind of import, each file's SHA-256, the rows, and
  what was created.

## Consequences
- The trial balance after posting equals the source to the cent (AC-R2). A file that does not
  balance, repeats an invoice, names an unknown account or has a malformed amount is refused
  before anything is created, with the row and the reason (AC-R3).
- R-3 (an accountant's trial balance, accounting packages) reuses the reader and the mapping step.
  R-4 adds a prior-year template.
- Income and expense balances in an opening trial balance are accepted, with a warning. This
  covers starting part way through a year.
