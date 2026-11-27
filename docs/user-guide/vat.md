# VAT

The VAT screen prepares a report for each of your VAT periods from the entries you posted. You
then file the return yourself on the Tax Department's portal. The platform never files
anything, and it is not tax advice.

## 1. Set your VAT periods
Open **VAT**. Under **VAT periods**, choose:
- **Length:** for example 3 months;
- **First day of a period:** for example 1 February, if your quarters run February to April,
  May to July and so on.

Then choose **Set VAT periods**.

If the Tax Department changes your periods later, enter the new length and the first day it
applies from, then choose **Change from this date**. The new periods must start where one of
your current periods would have started. Periods you have already reported on keep their
dates.

## 2. Prepare the report at the end of a period
In **Periods**, choose **Prepare report** next to the period. The report shows:
- **Totals:**
  - sales and their output VAT;
  - purchases and their input VAT;
  - the net VAT payable or refundable.
- **By VAT code:** the same figures for each VAT code and rate.
- **VAT accounts:** the period's VAT on each VAT account, and any payments or settlements.
- **Checks:** entries whose VAT does not match the code's rate, VAT without a taxable amount,
  and the like. Correct those entries (by reversal or adjustment), then choose **Regenerate**.
- **Lines:** every line behind the figures, which you can filter by VAT code.

A VAT code is applied to the entries where you choose it. For a sale, put the code on the income
line as well as on the VAT line, so that the taxable amount is counted.

### The return's boxes
At the top of the report, **VAT return** shows the 13 boxes you enter on the portal:
- Boxes 1–5 (VAT) to the cent;
- Boxes 6–11B (values) in whole euros, with the rounding next to them.

Box 3 is Box 1 plus Box 2, and Box 5 is Box 3 minus Box 4: payable when positive, a credit when
negative.

Choose **Lines** next to a box to see the lines that make it up and their total. In the
**Lines** table, **Boxes** shows where each line goes. Hover over it to see the rule. A line
marked **not in any box** is one the rules do not cover, for example an exempt purchase or the
value of an import. It is listed under **Checks**: ask your tax adviser how to report it.

**Checks** also lists:
- a tax point in another period;
- EU sales or purchases where the customer or supplier has no country or VAT number;
- a country that does not fit the code;
- Box 6 or Box 7 smaller than the boxes it includes, which a credit note can cause.

The box rules come from your specification and the Tax Department's guides. You checked them on
27/11/2026; each report records that, and that it is not a verification by a Cyprus tax
professional. The figures are prepared for you to check and
enter yourself.

### VAT codes and line details
VAT codes are grouped by kind in the entry form: domestic, zero-rated, exempt, EU goods and
services, reverse charge (EU services, non-EU services, domestic), imports and so on. Choose the
code that says what the transaction is, not only its rate: the VAT return puts an EU
acquisition in different boxes from a domestic purchase at the same rate. The old **RC** code
does not say which reverse charge applies; use one of the specific codes for new entries.

Once a line has a VAT code, open **VAT details** on it to enter:
- **Tax point**, only when it differs from the entry date;
- on an input VAT line, **Recoverable %** and **Non-recoverable VAT**, when only part of the VAT
  can be claimed. Enter the recoverable VAT as the line's amount. For example, VAT of 19.00 of
  which half is recoverable is a line of 9.50, with 50 and 9.50.

For EU sales and purchases, give each customer or supplier its **Country** (two letters, such as
GR) and VAT number under **Customers & suppliers**.

### Schedules and reconciliation
Under **Schedules** the report lists the transactions behind the return, one row per entry and
VAT code, with the customer or supplier, country and VAT number:
- **Sales** and **Purchases**;
- **EU trade:** goods and services supplied to, or received from, other member states;
- **Reverse charge:** EU acquisitions and reverse-charge services;
- **Imports**.

**Reconciliation** takes each VAT account from its opening to its closing balance. It then
compares the return with the ledger: Boxes 1 + 2 with output VAT, and Box 4 with input VAT. The
differences come from VAT lines that are in no box and from adjustments. If something is left
unexplained, the report says so. Payments, refunds and the settlement entry are shown separately
from Box 5.

### Imports
Import VAT paid at customs is claimed with an import code (IMP19, IMP9 and so on) on the input
VAT account. Each such entry needs its customs declaration:
1. Under **Entries**, attach the declaration (PDF or image) to the import entry.
2. On the VAT report, under **Imports**, choose the entry and enter:
   - the declaration's reference and date;
   - the taxable value and the import VAT it shows;
   - the attached declaration.

Then choose **Record import**, and **Regenerate** the draft.

The report checks that every import VAT claim has its record, that the VAT matches, and that
the taxable value at the rate gives that VAT. A declaration can be recorded only once, so its
VAT cannot be claimed twice. To correct a record, **Void** it with a reason and record it again.
This is not possible once its return is finalised; start a new version instead.

### VIES statements
If you sell goods or services to businesses in other EU member states, record each monthly VIES
statement as you filed it, under **VIES statements** on the report. For each statement, enter:
- the month, the date you filed it and the reference you received;
- each partner: its country, its VAT number, and the goods, services and triangular amounts.

Choose **Correction** for a corrected statement of a month already filed. The platform sends
nothing.

The report then compares each partner's supplies in the books with the statements. A partner
is marked as agreeing, as a rounding difference under one euro, as missing from the statements
or from the books, or as a difference to explain. The report also lists months with EU sales but
no statement, and compares the totals with Boxes 8A and 8B. Triangular amounts are shown
separately and compared with no box; ask your adviser how to report them.

### Purchases and sales in another currency
The return is in euros. Lines in another currency are converted at the rate you entered on the
line, the rate of the date and time of the purchase. The report states this, and each line keeps
its currency, original amount, rate, the rate's date and time and its source; the CSV download
has them too.

### Downloads
- **PDF:** every page shows the company, the period, the version and the page number.
- **Excel:** one sheet each for Summary, Sales, Purchases, EU Trade, Reverse Charge, Imports,
  Adjustments, Reconciliation, Exceptions and Tax Code Mapping, plus Codes and Lines. Amounts are
  numbers, and every sheet has filters.
- **CSV:** one row per line of the report, in UTF-8. The columns are `line_id`, `entry_id`,
  `entry_ref`, `date`, `account`, `code`, `category`, `kind`, `amount`, `counterparty`, `country`,
  `vat_no`, `reference`, `tax_point`, `recovery_percent`, `blocked`, `mapping`, `rule` and
  `rules`, then `box_1` to `box_11B` with the line's contribution to each box.

What the return covers, and what it does not, is listed in the
[coverage matrix](../vat/coverage.md).

## 3. Adjust if you must
If a box needs a change that the books cannot show, add it under **Adjustments** while the report
is a draft. Each adjustment needs:
- the box;
- the amount, with a minus sign to reduce the box;
- a reason;
- the evidence, for example "adviser's letter of 3 April, in Documents".

It counts only once someone other than you approves it. In a one-person workspace you approve it
yourself, and it is marked self-approved. The return then shows, for each box, the amount from the
books, the adjustment and the final amount. Prefer correcting the entries (by reversal or
adjustment) over adjusting a box.

## 4. Review, finalise, file, record
1. **Review**, after the period has ended. The figures are then frozen. If something is wrong,
   **Send back to draft** with a note saying why. You can then correct the entries, regenerate the
   report and review it again.
2. **Finalise.** This fixes the return and records which lines it includes. A line is never in
   two returns.
3. **Download PDF** or **Excel**, and file the return on the Tax Department's portal.
4. Enter the date you filed, the portal's reference, and where you keep the acknowledgement. Then
   choose **Record as filed**.
5. Optionally, **Prepare settlement entry**. This creates a draft entry that moves the period's
   input VAT into the output VAT account. Post it like any other entry.

In a one-person workspace you review and finalise your own report, and it is marked self-approved.
Otherwise someone else does both.

## 5. Entries that arrive later, and corrections
If entries are posted or reversed in a period after its report was prepared, the report shows
**Changes since this report was prepared**: the new lines and how each box would change. They
are never moved into this return or another one automatically.

To correct a finalised or filed return, choose **Start a new version**. It is prepared from the
books as they are now. It shows which version it corrects and how each box changed, and the
earlier version's approved adjustments are carried over for approval again. When the new version
is finalised, the earlier one is marked superseded. File the correction following the Tax
Department's procedure for corrections, with your adviser.

## What is still to come

Rates, codes and box rules show that they have not yet been checked by a Cyprus tax
professional.
