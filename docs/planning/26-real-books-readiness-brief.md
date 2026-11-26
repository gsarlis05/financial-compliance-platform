# 26 — Real books readiness: bringing your bank statements and your books in

Status: **APPROVED (2026-11-26)** by the owner ("Approved"). After version 1 the owner chose
"Real books readiness" as the next step and asked for **all four banks** (Bank of Cyprus,
Hellenic Bank, Eurobank Cyprus, Revolut Business) and **all ways** of bringing existing books in
(spreadsheets, accounting software, an accountant's figures, starting fresh).

## 1. Goal
The owner can move from synthetic data to their own books in an afternoon, without retyping:
- import any of the four banks' statement exports without setting up columns by hand;
- bring in the chart of accounts, opening balances, open customer and supplier invoices, and the
  prior year by month (for comparisons), from a spreadsheet, an accounting package's standard
  exports, or an accountant's year-end figures;
- see every import as a preview first, with every problem listed, and nothing reaching the books
  except as draft entries that go through the normal approval and posting.

## 2. Rules that do not change
- Nothing is posted by an import. Opening balances become **one draft opening entry** per entity;
  open invoices become draft entries on the receivable and payable accounts; both follow the
  normal workflow (or self-approval in a one-person workspace).
- Every import is previewed, validated and **balanced before** anything is created; a file that
  does not balance is refused with the difference shown.
- Money is `Decimal`; amounts in a file are read exactly, with the file's decimal separator.
- **No guessed formats.** The developer cannot see the banks' or software vendors' real export
  files. Formats are recognised from the columns a file actually has (by header names, in English
  and Greek). Each named bank or package preset is marked **"to be confirmed"** until it has been
  checked against a real export the owner provides (anonymised: real amounts and names replaced).
- Real files never enter the repository. Tests use synthetic files only.
- Imports are audited (who, when, which file by hash, what was created).

## 3. Work, in order (one issue and one PR each)
| # | Item | What "done" means |
|---|---|---|
| R-1 | **Bank statements: recognise the file** | Uploading a CSV detects the delimiter, the encoding (UTF-8, Windows Greek, Latin-1), the decimal separator, the date format and the columns from their headers (date, value date, description, amount or debit and credit, balance, reference, counterparty; English and Greek names). A preview shows the first rows as read and asks only about what is ambiguous (for example 03/04 as March or April). The result can be saved as the account's mapping. Presets for Bank of Cyprus, Hellenic Bank, Eurobank Cyprus and Revolut Business, each marked "to be confirmed". CAMT.053 keeps working unchanged. |
| R-2 | **Spreadsheet import: chart, balances, open items** | Downloadable templates (Excel and CSV) for: the chart of accounts; the opening trial balance; open customer and supplier invoices; customers and suppliers. Upload, preview with every error by row, map unknown account codes to the chart, then create: accounts and counterparties directly (they are set-up data), and the opening balances and open invoices as draft entries that must balance. |
| R-3 | **Accountant's figures and accounting packages** | The same import reads an accountant's year-end trial balance as delivered (account, name, debit, credit, or a signed balance), and the standard report exports of common packages (trial balance, aged receivables and payables, chart of accounts) through column recognition and the account-mapping step of R-2. Named presets (for example Xero, QuickBooks) are marked "to be confirmed". |
| R-4 | **The prior year by month** | Monthly balances per account for the year before the opening date, from the R-2 template, kept as prior-year comparatives (budget variance against the prior year, KPIs, the cash forecast's history) without creating entries in a closed year. |
| R-5 | **Guide and check** | A guide "Moving your books in"; synthetic example files for each template and for each bank preset; an end-to-end test that imports a full set and checks the trial balance equals the source; PROGRESS and a short report. |

## 4. Acceptance
- **AC-R1** A statement from each preset's synthetic file, and from a file with unfamiliar column
  names in Greek, imports without manual column set-up, or asks one clear question.
- **AC-R2** Opening balances, open invoices and the prior year imported from the templates give a
  trial balance equal to the source to the cent, with every created entry a draft until approved.
- **AC-R3** A file that does not balance, repeats an invoice, names an unknown account or has a
  malformed amount is refused before anything is created, with the row and the reason.

## 5. What is needed from the owner
1. **Approval of this brief.**
2. When convenient: one **anonymised** statement export from each bank you use (CSV and, if
   offered, CAMT.053), and, if you use accounting software, one anonymised trial balance and
   aged receivables export. These confirm the presets; until then they stay "to be confirmed".
