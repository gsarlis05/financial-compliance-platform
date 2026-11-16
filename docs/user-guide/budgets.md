# Budgets

**Cash & planning → Budgets.** A budget plans one fiscal year by month, for the whole entity
(annual), a department or a project.

## Create and fill in
1. Choose the fiscal year, give the budget a name and type, and select **Create budget**. For a
   departmental or project budget, choose the department or project. Every line of that budget
   belongs to it.
2. Add lines: a **taxonomy line** (for example *REV.SALES · Revenue — sales of goods*) or a
   specific **account**. Enter each month in the line's natural direction: income as income and
   costs as cost. Totals update as you type.
3. Select **Save lines**. You can save as often as you like while the version is a draft.

## Approve
- **Submit for approval** fixes the content. An approver (finance manager, partner or owner) then
  **approves** it, or **returns it to draft** with a comment saying what to change.
- With **segregation of duties** (on by default), the person who submitted cannot approve. A
  one-person business can switch it off. The switch is recorded in the audit trail, and every
  approval records whether it applied.
- **Lock** marks an approved version as the year's fixed baseline.

Approved and locked versions never change. The database refuses any edit.

## Revise
On the current version, give a reason and select **Start a revision**. This makes a new draft
with the same lines. When the revision is approved, the earlier version becomes *superseded*,
but it stays readable. The **original** budget (the first version ever approved) and the
**current** budget are labelled on the version buttons.

The **approval trail** lists who created, saved, submitted, returned, approved, locked or revised
each version, and when.

## Phasing
Instead of typing twelve months, choose a **phasing** method for a line and enter the annual amount:
- **Even:** the same each month.
- **Like last year:** in the shape of last year's posted actuals for that line (year-end closing
  entries are left out). If last year has none, the line is spread evenly and says so. This needs
  permission to see reports.
- **Profile:** your own weights, one per month (for example `1 1 1 2 2 2 1 1 1 2 2 2`).
- **Quantity × rate:** for example 3 people × 2,500 a month. One value is used for every month, or
  give one per month.

**Show months** previews the result without saving. The months always add up exactly to the annual
amount: each month is rounded to the cent once, and any rounding cent goes to the last month.

## Excel
- **Download as Excel** gives the version as a workbook. It is also the import template: one row per
  line, with the columns *Line* (taxonomy code), *Account* (account code), *Dimension*
  (`CODE:VALUE`, e.g. `DEPT:SALES`), *Note*, one column per month (`2027-01` …) and *Total*. The
  total is ignored on import.
- **Check and preview** reads an uploaded workbook and lists every problem by row and column, or the
  changes it would make. Nothing is saved until you select **Replace the lines with this file**. If
  the draft changed in the meantime, you are asked to preview again.
- **For safety:**
  - formulas, and text that starts with `=`, `+`, `-` or `@`, are refused (enter negative amounts
    as numbers);
  - workbooks with macros are refused;
  - files are limited to 5 MB and 5,000 rows.

  Exports put an apostrophe before such text, so it can never run in Excel.
- Imported lines are saved as manual monthly amounts.

## Department owners
A preparer can name an **owner** for each department (or project) of a budget. An owner with the
*budget holder* role:
- sees only the budgets that name them, and in them only their departments' lines, in the page,
  the API and the Excel download;
- can edit and import those lines while the version is a draft, and nothing else;
- cannot submit, approve or see other departments.

## Coming next
Budget-versus-actual variance with explanations (M4-3).
