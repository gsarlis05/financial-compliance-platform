# ADR-0023: Budget phasing, spreadsheet import and department owners
Status: **Proposed** (M4-2; awaiting product owner review in PR) · Date: 2026-11-04
## Context
AC-BU2 asks that phasing methods sum exactly to the annual input, with the rounding residual on the
last period. AC-BU3 asks for an Excel import that validates and previews, and never evaluates
formulas (threat T9). AC-BU6 asks that department-scoped owners see and edit only their department.
## Decision
- **Phasing is server-side and pure** (`budgeting/phasing.py`, Decimal only):
  - Months 1 to n−1 are rounded half up once. The last month takes the residual.
  - If that residual would have the opposite sign to the annual amount (a tiny amount spread over
    many months), months 1 to n−1 are rounded toward zero instead.
  - Property tests check both rules.
  - *Seasonal* weights are last year's posted actuals per month (closing entries excluded), read
    through `reporting`. Negative months weigh zero. Without history, the line is phased evenly
    and the note says so.
  - The method and its parameters are stored on the line, so they are part of the content hash
    that approval checks.
- **Import:**
  - only our own template (`.xlsx`);
  - zip checks before parsing (5 MB, 200 parts, 50 MB unpacked, no `vbaProject.bin`);
  - openpyxl in read-only mode with defusedxml, `data_only=False`, so formulas are *seen* and
    rejected, never computed;
  - text starting with `= + - @`, tab or CR is rejected;
  - every problem is reported with row and column.

  Preview and apply are two calls with the same file. Apply must send the preview's draft hash,
  so an edit in between is never overwritten unseen.
- **Export:** text cells are neutralised with a leading apostrophe; totals are values, not
  formulas; a line states the nature (BUDGET).
- **Department owners:**
  - New `budget_holder` role with `budget.department` only, plus reading the chart and periods.
  - Routes that owners share declare `budget.department`, which every reading role also holds.
  - The service decides the scope: full with `budget.read`/`budget.edit`, otherwise only the
    owned dimension values. An owner's save replaces only their lines and leaves the others
    untouched.
  - A reader without edit rights gets 403, never a misleading 404.
## Consequences
- Imported lines become MANUAL lines. A phasing method is chosen in the grid, not in the file.
- Seasonal phasing needs `reports.read`, so budget holders cannot use it (a clear 422).
- No new dependency: openpyxl and defusedxml were already used for statement exports.
