# Milestone 6 report: three-statement projections and rolling forecasts

Status: **complete, awaiting product owner review** (PRs #141–#146, stacked after Milestone 5;
each is reviewable on its own). **No environment exists beyond local development and CI. Nothing
was created on AWS, and no migration has been applied anywhere else.** Brief:
[planning doc 19](planning/19-milestone-6-brief.md); specification: planning doc 10 §1, §2.4 and
§4 (approved), on the planning branch (PR #1), which is not yet merged.

**Owner decisions of 2026-11-15** replace the simplified defaults listed for confirmation below
(depreciation, Cyprus corporate tax, debt, rolling forecasts, goals, currency) and require
independent professional validation of the projection engine. They are planned in
[planning doc 20](planning/20-milestone-6-follow-up-brief.md) (issues #80, #147–#154). **Until that
validation passes and a qualified reviewer signs it, the projection engine is not production-ready:**
every projection screen and export says so.

## What you can do now
On top of Milestones 1 to 5, you can:
- **Keep a fixed-asset register.** Record what the business owns; depreciation is worked out for
  you (straight-line or declining balance), and each month's depreciation is **prepared as a draft
  entry** that goes through the normal approval. The register never posts by itself.
- **Write down your assumptions** month by month: revenue and costs per line, gross margin, payment
  days, investment, borrowing, tax, dividends, minimum cash and a credit facility. Start from last
  year's actuals (with growth), the approved budget, or empty; approve; revise as new versions.
- **See where the business will be in one to three years, on all three statements.** A projected
  income statement, balance sheet and cash flow statement start from your actual balance sheet and
  always agree: six checks run on every projection, and one that fails cannot be published.
  Select any figure to see where it comes from; export the statements to Excel.
- **Keep a rolling forecast** of the next 12 or 24 months that re-runs itself when entries are
  posted or a month closes, keeps the earlier forecasts, and shows how accurate they were.
- **See the full year at a glance**: actual months from the books, then forecast months from the
  published projection, each column marked, with quarters and the year as exact sums. Goals use
  the published projection as their likely outcome.

Try it with `make demo` ([demo script](demo.md)); its 33 steps now include the fixed-asset
register and its prepared depreciation, the assumptions, the projection (checked and published),
the full-year outlook and the rolling forecast. User guides:
[fixed assets](user-guide/fixed-assets.md) and [projections](user-guide/projections.md).

## Items
| Item | PR | What |
|---|---|---|
| M6-1 Fixed assets | #141 | `assets` module (a sub-ledger): register, straight-line and declining-balance schedules (the last month takes the remainder), disposals, monthly depreciation prepared as one draft entry through the ledger's public interface, never twice (ADR-0037) |
| M6-2 Assumption sets | #142 | `projections` module: versioned sets of drivers by month, started from actuals, the budget or empty, with the source of every value; DRAFT → APPROVED → SUPERSEDED guarded by the database; grid screen (ADR-0038) |
| M6-3 Projection engine | #143 | pure three-statement engine in doc 10 §4.1's order, rounding per line, six invariants on every run, lineage per line, run as a reproducible calculation run pinned to the ledger watermark; property tests and a 24-month golden model (ADR-0039) |
| M6-4 Rolling forecasts | #144 | per-entity setting; stale on postings, a closed month or a new approved version; hourly re-runs as the user who set it up; history; accuracy at 1, 3 and 6 months (ADR-0040) |
| M6-5 Outlook | #145 | the fiscal year as actual months plus forecast months with a nature per column, fiscal quarters and the year as exact sums; goals use the published projection (ADR-0041) |
| M6-6 Screens | #146 | Projections (statements with natures, checks, explain a line, cash chart with a table, publish, Excel export, rolling forecast and accuracy) and Full-year outlook; this report |

## Acceptance criteria (brief §5)
| Criterion | Evidence |
|---|---|
| **AC-FA1** Schedules match hand-computed tables to the cent; total = cost − residual; disposals stop depreciation | `tests/assets/test_schedule.py` (10 tests: hand-worked straight-line and declining-balance tables, remainder month, disposal, property test over random assets) |
| **AC-FA2** Prepared entries are drafts needing normal approval; never prepared twice; nothing posted by the register | `tests/assets/test_assets.py` (draft only, unique per month, re-prepare only after void or reject, posted through the workflow); demo step posts January 2027 through the reviewer |
| **AC-PJ1** Every period satisfies all six invariants exactly, for any valid assumption set and on the golden model | `tests/projections/test_engine.py`: property test over random drivers and balanced openings (150 examples); golden model |
| **AC-PJ2** Period 1 opens on the actual balance sheet, line for line | `test_run_publish_and_reproduce` (opening = books: cash 100, receivables 300, retained earnings 400); engine check `opening_equals_previous_closing` |
| **AC-PJ3** The golden 24-month model matches to the cent | `test_golden_24_months` (closed forms worked out by hand in the test). **Professional sign-off pending (yours to arrange)** |
| **AC-PJ4** Same inputs give the same hash; later postings do not change a stored run | `test_run_publish_and_reproduce` (same input and output hashes; a posting after the watermark leaves the stored run's values unchanged; a new run has a new watermark) |
| **AC-PJ5** An approved set and a published projection cannot be changed (database) | `tests/projections/test_assumptions.py` (database guards on sets and values); published runs are protected by the calculation-run guards from M3-2 |
| **AC-PJ6** A failing run is INVALID, says where, and cannot be published | `test_an_invalid_run_says_where_and_cannot_be_published` (`balance_sheet_balances@2027-03`; publish refused with 409); `test_a_broken_statement_fails_and_says_where` |
| **AC-RF1** A posting makes the rolling forecast stale; the job creates a new run and keeps the old; accuracy for closed months | `tests/projections/test_rolling.py` (4 tests; accuracy worked by hand: forecast 1,200, actual 1,000, error 200, 20.00%) |
| **AC-OL1** Actual months from the ledger, forecast months from the projection, a nature per column, quarters and the year exact sums | `tests/projections/test_outlook.py` (natures per column, every quarter and the year re-added in the test, cash equal to the projection's balance sheet); goals use the projection (method PROJECTION, likely revenue 4,300) |
| **AC-UI1** Every new screen passes axe, shows nature by more than colour, and has a table alternative to each chart | `fixedassets.test.tsx`, `assumptions.test.tsx`, `projections.test.tsx` (axe with no violations; natures as words plus border style; the cash chart has a text description and the balance-sheet table holds its figures); live checks |

## Database changes (Milestone 6)
| Module | Migrations | Content |
|---|---|---|
| assets | 0001–0002 | fixed assets, depreciation runs and run lines; terms lock once depreciation is prepared; runs can only be cancelled; run lines append-only |
| projections | 0001–0004 | assumption sets and values (values change only in drafts; approved sets only move to superseded; nothing deleted); rolling forecast settings; `projections_rolling_tenant_ids()` (returns IDs only) |

Every new tenant table has FORCE row-level security and composite tenant keys. Projections
themselves use the existing calculation-run tables. Migrations were applied locally only.

## Security controls added
- **The register never posts.** It prepares drafts through the ledger's public interface; the
  normal segregation of duties applies.
- **Planning still never imports the ledger.** Projections read actuals only through `reporting`
  (import contracts enforced in CI).
- **Projections cannot be published unless every check holds**, and published runs never change.
- **The rolling-forecast job sees only workspace IDs** through a narrow SECURITY DEFINER function,
  then works inside each workspace's own row-level security context as the user who set it up,
  with that user's current permissions; a refused user is skipped and logged.
- **Exports are formula-safe** and audited, and say on every sheet that the figures are a
  projection, not actual results.

## Quality
Measured on 2026-11-15 on the M6-6 branch (`make test`, fresh database):
- Backend: **1,203 tests**, **96.6%** line coverage overall. In the full run 1,202 passed; the check that the published API document is current failed only because I regenerated that document while the run was in progress, and it passes when re-run with the projection, goal and demo tests.
- Frontend: **64 tests**, including axe on every new screen; ESLint strict, `tsc`, build.
- `make lint` and `make security` are green; every PR's CI is green on its head.
- **Live checks** with MFA sign-in on the local stack for every new screen. They and the tests
  found and fixed, among others:
  - duplicate API schema names across modules (twice);
  - a demo that left a depreciation draft unposted;
  - the view buttons (month, quarter, year) not showing which one is selected;
  - rolling-forecast runs that could not be told apart from projections you ran yourself.

## Known limitations
- **Depreciation conventions are fixed**: monthly, from the month after acquisition; no
  revaluation, impairment or tax depreciation. Disposal entries are booked by hand.
- **The engine is deliberately simple**: interest on opening balances (no averaging), no loss
  carry-forward, no VAT balances, dividends as amounts (not a payout %), M3 loan schedules not yet
  used as financing inputs. Lines the drivers do not cover are held at their opening balance.
- **Rolling forecasts** repeat the set's value for the same calendar month beyond its horizon (no
  growth), and can be up to an hour behind a posting (marked out of date until re-run).
- **Single currency (EUR).** M6-0 multi-currency (#80) was not built: it is built only once you
  confirm you need another currency (decision 4 below).
- **Greek wording** for all new screens and the Excel export needs a native speaker's review.

## Decisions and approvals needed from you
1. **Review and merge**, in order: PR #1 (planning documents), the earlier stacks, then
   #141–#146 (this report is in #146).
2. **ADRs to accept or change:** 0037 (fixed-asset register), 0038 (assumption sets), 0039
   (projection engine), 0040 (rolling forecasts), 0041 (full-year outlook).
3. **Defaults to confirm** (brief §3 and the ADRs):
   - depreciation starts the month after acquisition; the last month takes the remainder;
   - tax on profit is paid in the first month of the next fiscal year, with no relief for losses;
   - interest on the debt at the start of each month;
   - the rolling forecast re-runs hourly; accuracy at 1, 3 and 6 months;
   - goals use the published projection ahead of the budget.
4. **Currencies:** does the business use any currency other than EUR? If not, #80 is closed as not
   needed; if yes, M6-0 is built next.
5. **Sign-offs:** the golden 24-month projection (AC-PJ3), and still open from earlier milestones,
   the golden 13-week forecast (AC-CW5) and the golden goal figures (AC-GO2).
6. **Gate P** (pilot) items from the Milestone 5 report are unchanged and still need you.

Milestone 7 waits for your review of this milestone.
