# ADR-0043: Tax rules are sourced, versioned, jurisdiction-specific reference data
Status: **Proposed** (M6F-2, #147; awaiting product owner review in PR) · Date: 2026-11-15

## Context
Owner decision D4 (2026-11-15): Cyprus is the first tax jurisdiction; corporate tax must follow
the Cyprus legislation (15% from 2026, losses carried forward seven years from 2026, provisional
instalments, the final balancing payment and their deadlines), and tax rules and deadlines must be
configurable, version-controlled and jurisdiction-specific. The project's rules forbid inventing
regulations or citations (CLAUDE.md), and owner decision #93 requires a qualified tax professional
to verify tax data before it is relied on.

## Decision
- **`taxrules` module, `taxrules_rule_set` table.** One row per jurisdiction, tax and window of
  tax years (`effective_from` to `effective_to`, inclusive): rate; loss carry-forward years (for
  losses *arising* in those tax years); the month the tax year starts; provisional instalments as
  month, day and share of the year's tax; the final payment as years after the tax year, month
  and day; sources (publisher, title, URL, note); verification status, with who verified and when.
- **Global reference data**, read-only for the runtime role, seeded by migrations from
  `taxrules/data/<jurisdiction>.json` and idempotent. Seeding never changes the verification
  fields; a professional's confirmation is recorded by its own migration.
- **Database guards:** windows of the same jurisdiction and tax never overlap (trigger), so the
  rule set in force for a day is unique; a rate is a fraction below 1; a set can be marked
  verified only with the verifier's name and date.
- **Resolution:** `rules_for(jurisdiction, day)` returns the set in force; engines pin the set's
  values and id in their run inputs (`as_refs()`), so a later change to the data never changes a
  stored run.
- **Cyprus seed (pending verification, #154):** `CY:CIT:2020` (2020–2025: 12.5%, 5 years) and
  `CY:CIT:2026` (from 2026: 15%, 7 years); provisional instalments 31 July and 31 December
  (half each); final payment by 1 August of the following year. Values come from published
  professional summaries (EY, PwC, ITR, RSM, IBCCS); the primary legal texts could not be opened
  from the development environment. The seven-year period is applied to losses arising from
  2026; how it applies to earlier losses is an open question for the tax professional. Years
  before 2020 are not seeded, so a projection reaching back further fails clearly rather than
  guessing.
- **Not modelled:** late-payment interest and penalties (projections assume payment on time) and
  the underestimation charge on provisional tax (shown as information in the brief).

## Consequences
- Another jurisdiction is a new data file and seed migration, not code.
- Every screen and export that uses a rule set shows its verification status (from M6F-5).
- Correcting a value after verification is a migration with its source, reviewed in a PR.
