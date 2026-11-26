# Example files for moving your books in (synthetic)

Every name, number and amount in these files is **invented**; names are marked "(Demo)". They
show what each import reads, and the test `backend/tests/onboarding/test_examples.py` imports
all of them end to end. Never put real files here.

| File | Step on Bring your books in | What it shows |
|---|---|---|
| `chart.csv` | 1. Chart of accounts | Three accounts added to the Cyprus business chart; one identical row is skipped |
| `counterparties.csv` | 2. Customers and suppliers | Three customers and two suppliers |
| `opening-balances.csv` | 3. Opening balances (the template) | The trial balance at 1 January 2026 |
| `open-items.csv` | 3. Open invoices (the template) | The invoices behind receivables (with a credit note) and payables |
| `accountant-trial-balance.csv` | 3. Instead of the template | The same books as an accountant delivers them at 31 December 2025: title, headings, codes and names in one column, the year's income and expense, a total. Carry the result into 3200 |
| `aged-receivables.csv` | 3. Instead of the open invoices | An aged receivables report: contacts by name, ageing buckets, subtotals, dates with month names |
| `aged-payables.csv` | 3. Instead of the open invoices | An aged payables report with **month-first** dates (choose month first) |
| `prior-year.csv` | 4. Prior year by month | A monthly trial balance of 2025: every month balances and December equals the opening balances |

Both routes for step 3 give the same opening entry.

## Bank statements
One file per bank preset on **Bank**. Each has a **different shape**, chosen to exercise the
recognition:
- Greek headers after account details, with a decimal comma;
- English debit and credit columns;
- a signed amount with Greek headers;
- timestamps.

**They are not the banks' real export layouts**, which the developer has not seen. The presets
stay "to be confirmed" until checked against a real, anonymised export.

| File | Preset |
|---|---|
| `bank-statement-bank-of-cyprus-preset.csv` | Bank of Cyprus |
| `bank-statement-hellenic-bank-preset.csv` | Hellenic Bank |
| `bank-statement-eurobank-cyprus-preset.csv` | Eurobank Cyprus |
| `bank-statement-revolut-business-preset.csv` | Revolut Business |
