# ADR-0072: Correcting the rules per entity, from a date
Status: **Accepted** (T-2, #255; brief 27) · Date: 2026-11-27 · Builds on ADR-0071

## Context
On 2026-11-27 the owner checked the VAT codes, the VAT return's box rules and the corporate tax
rules, and asked to keep the option to correct them, on a screen, if anything changes. The rules
are global reference data, versioned and seeded from files, and read-only for the runtime role.
Earlier returns and runs must never change.

## Decision
- **Corrections are entity data in one table**, `taxrules_correction`.
  - Each row has its kind, the rule it corrects (`target`), the start, the values, a source
    (required) and a note.
  - The table has FORCE RLS and a composite tenant key.
  - A database trigger refuses any update or delete.
  - Each correction is audited, with the one it replaces.
- **Order.** A correction cannot start before the latest one for the same rule, so the history
  only moves forward. One that starts on the same day as the latest supersedes it; that is how a
  mistake is corrected.
- **Each owning module checks its own kind**, then calls `taxrules.add_correction`. The
  dependencies run one way only (ledger → taxrules, tax → taxrules), and the import contracts
  still hold.
  - **VAT code** (ledger):
    - What it can change: the rate (a fraction to 4 decimals, or none), the treatment, the
      category (one the catalogue already uses) and the names.
    - Which code: the code must exist in the entity's jurisdiction.
    - When it applies: to a line whose tax point, or else accounting date, is on or after the
      start.
    - Where it shows: the code list for a date shows the corrected values with the start and
      source. The VAT lines the return is built from carry the corrected treatment, rate and
      category, and the correction used.
  - **Box rule** (tax):
    - What it can change: for a category and line kind, either the boxes the line goes to (never
      Box 3 or 5, which are worked out) or "excluded".
    - When it applies: to a VAT return whose period starts on or after the start.
    - Where it shows: in the line's rule text ("Corrected from …: source"), in a new
      `GET …/vat-box-rules?on=` route, and in the exports' mapping table.
  - **Corporate tax** (taxrules):
    - What it is: a full rule set (rate, loss years, tax year start, instalments whose shares add
      up to 1, final payment).
    - When it starts: on the first day of a tax year.
    - How it applies: it replaces the global rule sets from its start, and the global set's
      window is cut the day before. `rules_for(…, entity_id=)` and `rule_sets(…, entity_id=)`
      apply it, and projection runs pass the entity.
- **Pinned.** A VAT report's snapshot keeps the box rule corrections in force for its period
  (`return.corrections`) and the code corrections its lines used (`code_corrections`). A
  projection run pins the rule set it used in its inputs, as before; a corrected set's id is
  `CORRECTION:<id>`. Earlier reports and runs keep what they used. A draft report regenerated
  after a correction uses it.
- **Who.** A new permission, `tax.rules.correct`. Only the owner and a firm partner hold it; they are the two roles that hold every permission. An accountant, a finance manager or a reviewer does not.
- **The screen.** Setup → Tax rules shows:
  - who checked the rules (ADR-0071);
  - the VAT codes on a date;
  - the box rules for returns starting on a date;
  - the corporate tax rule sets;
  - a form for each kind of correction;
  - the history.

  Rates are typed as percentages and turned into fractions by moving the decimal point, never
  through floating point.

## Consequences
- AC-T2 and AC-T3 hold:
  - a correction applies from its date to what is prepared after it;
  - earlier figures stay as they were;
  - a correction without a source, starting before the latest, not at the start of a tax year,
    with bad shares, with an unknown code or category, with formula boxes or changing nothing is
    refused with the reason.
- The projection engine itself is code. Its inputs are corrected on their screens: assumptions,
  these tax rules, allowance classes and debt.
- A correction applies to one entity. Another entity of the same workspace keeps the global
  rules until it is corrected too.
