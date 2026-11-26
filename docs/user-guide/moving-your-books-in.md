# Moving your books in

This guide takes you from the demo data to your own books, without retyping. Everything happens
on two screens:
- **Bookkeeping → Bring your books in**, for the chart of accounts, customers and suppliers, the
  opening balances and the prior year;
- **Bookkeeping → Bank**, for bank statements.

Nothing you import is posted on its own. Each file is checked first, and every problem is listed
with its file, row and column. When the opening balances are imported, they become **one draft
entry**, which you approve and post as usual.

Example files for every step are in [`examples/books/`](../../examples/books/). They are
synthetic, so you can use them to try every step first.

## Before you start
1. **Create the entity and its first fiscal year.** Under Settings → Fiscal years, the first
   year starts on your opening date, for example 1 January 2026. The prior year is the months
   before it.
2. **Pick the chart.** Apply the Cyprus business chart, or start empty and import your own (step
   1).
3. Decide **where your figures come from**:

| Your books today | Use |
|---|---|
| A spreadsheet | The templates (download each one from the screen, as Excel or CSV) |
| An accountant | Their year-end trial balance as delivered, and their list of unpaid invoices |
| Accounting software | Its trial balance and its aged receivables and aged payables reports, exported to Excel or CSV |
| Starting fresh | Only the chart (step 1) and the bank balances in the opening trial balance (step 3) |

You can mix sources: for example, your accountant's trial balance with your software's aged
receivables report.

## Step 1: the chart of accounts
Use the template, or your software's chart export. The columns are found by their names:
- Code, Name and Type are required.
- Parent code, Postable, Control, VAT role and Greek name are optional.

Types are read as packages write them: "Current Asset", "Accounts Receivable", "Revenue",
"Overhead" and so on. "Accounts Receivable" and "Accounts Payable" make the customer and supplier
control accounts.

Accounts already in the chart with the same name and type are skipped. If an account has the same
code but a different name, you are told. Correct the file, or the existing account.

## Step 2: customers and suppliers
Each customer or supplier needs a Code, a Name and a Kind (Customer, Supplier or Both). You can
also give a VAT number, an email address, payment terms and a country.

You may skip this step if your aged receivables and payables reports name them (see step 3).

## Step 3: opening balances and open invoices
1. Choose **where the files come from**: your own spreadsheet or accountant, Xero, or QuickBooks.
   Xero and QuickBooks only set how dates are read. Neither has yet been checked against a real
   export, so check the preview carefully.
2. Choose the **opening date**. It is the first day of your first fiscal year.
3. Add the **trial balance** at that date:
   - the template;
   - your accountant's trial balance as delivered (headings, subtotals and totals are fine, and
     so are Dr and Cr);
   - or your software's trial balance report.

   The file's total is checked against its lines.
4. For the receivables and payables accounts, add **the invoices still open**: the open-invoices
   template, or your software's aged receivables and aged payables reports. They must add up to
   those accounts' balances. They become the open items, which you then match to payments.
5. If the trial balance still shows **the year's income and expense** (a year-end trial balance
   does), choose the retained earnings account to carry them into.
6. **Check the file.**
   - For an account the chart does not have, choose which chart account it goes to. Several old
     accounts can go to one.
   - For customers or suppliers that are not set up yet, tick **Create them with this import**.
7. When the check is clean, **create the draft entry**. Open it, then approve and post it.

Once it is posted, the trial balance on the opening date equals your file to the cent.

## Step 4: the prior year by month (optional)
To compare with last year (budget against the prior year, KPIs, statements), import a monthly
trial balance of the months before your books start. The template lists those 12 months. Each
cell is the account's balance at the end of the month. Income and expense can be written year to
date, or as each month's own amount.

Every month must balance, and the last month must agree with your opening balances. These figures
are kept for comparisons only; they never become entries. Importing again replaces them.

## Bank statements
On **Bank**, choose the account and a CSV export from your bank. The import works out the
following from the file:
- the encoding, including Windows Greek;
- the separator;
- where the header is, after any account details;
- which column is which, from English or Greek names;
- the decimal separator and the date format.

It asks only about what the file leaves open, for example whether 03/04/2026 is the 3rd of April
or the 4th of March. Then it shows the first lines as they will be imported.
**Save this layout and import** keeps the layout for that account.

There are presets for Bank of Cyprus, Hellenic Bank, Eurobank Cyprus and Revolut Business. They
only break ties, and they are **to be confirmed**: they have not been checked against real exports
from these banks yet. CAMT.053 files work as before.

## Help us confirm the presets
Send one **anonymised** export from each bank you use, and from your accounting software if you
use one (a trial balance and an aged receivables report). Replace real names, account numbers
and amounts first. These files confirm the presets; until then they stay "to be confirmed".
Never put real files into the repository.

## If something is refused
| The message says | What to do |
|---|---|
| "is not an amount this import can read unambiguously" | Write `1250.00` or `1.250,00`, not `1,250` or `1.250` |
| "reads only month first" (or day first) | Choose the other date order for the file |
| "does not balance" | The file's debits and credits differ by the amount shown |
| "is not in the chart" | Map the account to a chart account, or import the chart first |
| "the open invoices … add up to" | The invoices listed do not add up to the account's balance |
| "is already in the books" | That invoice was imported before |
| "No fiscal year contains" | Create the first fiscal year first |
| "Formulas are not accepted" | Copy the cells and paste them as values |
