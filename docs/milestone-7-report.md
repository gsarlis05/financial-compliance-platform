# Milestone 7 report: scenarios, sensitivity and advanced KPIs

Status: **complete, awaiting product owner review** (PRs #183–#189, stacked: each targets the one
before it, starting from `main`; each is reviewable on its own). **No environment exists beyond
local development and CI. Nothing was created on AWS, and no migration has been applied anywhere
else.** Brief: [planning doc 21](planning/21-milestone-7-brief.md), approved 2026-11-16 ("Continue
as you think it's better"), so its defaults in §3 were taken.

**The projection engine is still pending independent professional review** (issue #153). Scenarios,
sensitivity and the working-capital view all run on it, so every one of their screens and exports
says so, and none of their figures is called certified or validated.

## What you can do now
On top of Milestones 1 to 6, you can:
- **Ask "what if?"** Take an approved assumption set and change some of its assumptions: revenue
  or costs by a percentage or an amount, payments arriving later, a new loan, new hires, an
  investment, a one-off payment, higher interest rates. See the three statements next to the plan,
  the difference on every line, a cash chart, and **what each change did**: the effects add up
  exactly to the total. Every scenario figure is called **hypothetical**, in words and with a
  dotted line, and a scenario never changes the plan, a budget, a forecast or the books.
- **Share, copy and archive scenarios.** Drafts are yours alone; shared scenarios can be seen by
  anyone with planning access. Turn a scenario into a **new draft assumption set**, which then
  needs the normal approval.
- **See which assumptions matter most**: a tornado chart moves every assumption down and up by the
  same percentage and ranks them by how much the result moves (lowest cash, cash at the end, months
  before a shortfall, EBITDA or net income); or move one assumption over a range.
- **See working capital month by month**: receivables, stock and payables, the days behind them
  and the cash conversion cycle, next to the days seen over the last 12 months; and work out what
  N days are worth in cash.
- **Test a goal against up to three shared scenarios**, side by side with the plan. The goal itself
  never changes and nothing is saved.
- **Four more KPIs** (library CORE@1.1): net debt / EBITDA, debt service coverage (DSCR),
  receivables turnover and inventory turnover; and the whole library on projected and scenario
  years.
- **Export a comparison to Excel**, in English or Greek.

Try it with `make demo` ([demo script](demo.md)); its 34 steps now include a scenario on the
approved assumptions (revenue 15% lower from July 2027, rates 2 points higher), shared, compared
and run through a tornado. User guides: [scenarios](user-guide/scenarios.md),
[goals](user-guide/goals.md) and [KPIs](user-guide/kpis.md).

## Items
| Item | PR | What |
|---|---|---|
| M7-1 Scenario model | #183 | `scenarios` module: a scenario on an approved set, eight typed overrides validated in plain words, DRAFT → SHARED → ARCHIVED, copy and rebase; database guards; the brief (ADR-0049) |
| M7-2 Scenario runs | #184 | overrides applied to a copy of the engine input, then the unchanged engine (kind `SCENARIO`, never publishable); comparison by month, quarter or year; lineage by override; what changed and why; liquidity; saved runs; promotion to a draft set (ADR-0050) |
| M7-3 Sensitivity | #185 | one variable over up to 11 steps, and tornado (ties by driver name); cached by input hash; quotas per user and workspace; time limit (ADR-0051) |
| M7-4 Working capital | #186 | receivables, stock, payables, DSO/DIO/DPO and the cash conversion cycle by month against observed days; what N days are worth by two engine runs |
| M7-5 Goals against scenarios | #187 | goal engine v3: method `SCENARIO`, nature `HYPOTHETICAL`, up to three shared scenarios next to the base, computed in memory |
| M7-6 Advanced KPIs | #188 | KPI library CORE@1.1 (`ltm_flow`), KPIs on projected and scenario years; CORE@1.0 sets unchanged (ADR-0052) |
| M7-7 Screens | #189 | Scenarios, Sensitivity, Working capital and goals against scenarios; Excel export of a comparison; the demo step; this report |

## Acceptance criteria (brief §5)
| Criterion | Evidence |
|---|---|
| **AC-SC1** Eight override types validate their parameters in plain words; outside the horizon refused | `tests/scenarios/test_overrides.py` (`test_every_type_is_covered`, `test_problems_are_refused_against_their_parameter`: each problem named against its parameter); `test_base_rules_rebase_and_permissions` |
| **AC-SC2** No overrides gives exactly the base's results and output hash | `test_runs.py::test_no_overrides_is_the_base_exactly` (property test over random approved inputs) |
| **AC-SC3** Every month of any scenario satisfies the invariants; a failing one is INVALID and says where | `test_runs.py::test_any_scenario_keeps_the_invariants_and_its_effects_add_up` (property test); `test_timing_capex_and_refusals`; demo: "all checks hold" |
| **AC-SC4** Every scenario value HYPOTHETICAL in API, screens and export; lineage per changed figure; what changed sums to the total | `test_runs.py::test_lineage_names_each_override_and_its_effect`, `test_runs_api.py::test_comparison_save_and_promote` (July revenue changed by override 1 only; effects add up); `test_export.py` (Nature row, note on every sheet); `scenarios.test.tsx` (label in words, dotted line) |
| **AC-SC5** A scenario never changes its base or any approved or published object; promotion makes a draft only | `test_scenarios.py::test_the_database_keeps_scenarios` (guards as the runtime role); `metrics.calc.publish` refuses kind `SCENARIO`; `test_comparison_save_and_promote` (promotion → DRAFT set) |
| **AC-SC6** Same base, overrides and engine version give the same hash; new postings don't change a saved run | `test_comparison_save_and_promote` (saving again gives the same output hash); `test_a_saved_run_ignores_later_postings` (a posting after the save leaves the run's watermark, hash and values unchanged; a new run includes it) |
| **AC-SE1** Results equal single engine runs; tornado ranks by swing, ties by name | `test_sensitivity.py::test_results_equal_single_engine_runs`, `test_tornado_by_hand_and_ties_by_name` |
| **AC-SE2** Quotas, time limit and caching; 25 drivers on 24 months within target | `test_api_cache_quota_and_bases` (second request from the cache; 429 with a message past the quota; time limit). Measured on the demo's 24-month set: every distinct driver (19; the list cannot reach 25) at ±7%, **0.83 s** (39 engine runs), **0.22 s** from the cache, against a 30 s limit |
| **AC-WC1** View equals the projection's balance sheet; N days worth equals two engine runs | `test_working_capital.py::test_table_by_hand`, `test_value_of_days_by_hand` |
| **AC-GS1** A goal against a scenario uses its figures, says so, is shown next to the base; the goal is unchanged | `tests/scenarios/test_goal_outlooks.py::test_goal_against_scenarios`; live check (Revenue 500k: base 1,320,000.00, scenario 1,214,400.00 hypothetical) |
| **AC-KP6** New KPIs match hand-worked examples; not meaningful where defined; older sets unchanged | `tests/kpi/test_kpis.py` (hand values; EBITDA ≤ 0 and no debt service are NM); `test_projected_kpis.py::test_library_on_a_projected_year` (hand values on the projection); CORE@1.0 sets keep their values |
| **AC-UI2** Every new screen passes axe, hypothetical by more than colour, table alternative to each chart, no horizontal scroll at phone width | `frontend/src/scenarios.test.tsx` (5 tests, axe with no violations on all four screens); live checks at 1280 px and 390 px (scroll width equal to the window on every screen) |

## Database changes (Milestone 7)
| Module | Migrations | Content |
|---|---|---|
| scenarios | 0001–0002 | scenarios and their overrides; a scenario starts as a draft on an approved set of the same entity; its entity, base, author and origin never change; overrides change only in drafts; nothing is deleted |
| kpi | 0005 | library CORE@1.1 (23 definitions) alongside CORE@1.0 |

Every new tenant table has FORCE row-level security and composite tenant keys. Scenario and
sensitivity runs use the existing calculation-run tables. Migrations were applied locally only.

## Security controls added
- **A scenario cannot reach the plan or the books.** It changes a copy of the engine input in
  memory; its runs are kind `SCENARIO`, which publishing refuses; promotion creates a draft that
  needs the normal approval.
- **Drafts are private** to their author; shared scenarios need planning access; another user's
  draft is not found rather than refused.
- **Sensitivity cannot be used to exhaust the server**: per-user and per-workspace quotas (HTTP
  429 with a message), a 30-second limit per request, at most 25 drivers and 11 steps, and results
  cached by input hash.
- **Planning still never imports the ledger**; the scenarios module uses only the public
  interfaces of projections, goals, KPIs and metrics (import contracts enforced in CI).
- **Exports are formula-safe** (threat T9), audited, need the right to export reports, and say on
  every sheet that the figures are hypothetical.

## Quality
Measured on 2026-11-16 on the M7-7 branch, on a fresh test database (`make test`, `make lint`,
`make openapi-check`, `make security`, `make validation`, all passing):
- Backend: **1,303 tests passed**, **96.24%** line and branch coverage overall; the `scenarios`
  module **98.43%**. The calculation engines `apply.py` and `sensitivity.py` were first at 96.70%
  and 98.70% branch coverage; tests for the missing branches (a month shift that loses nothing,
  rate changes on the facility or an unnamed loan, a loan rate below zero, an unknown output)
  bring both to **100%**, as the brief requires.
- Frontend: **69 tests**, including axe on all four new screens; ESLint strict, `tsc`, build.
- Security: Semgrep 0 findings; gitleaks no leaks. Validation package: all six scenarios match
  the independent model to EUR 0.01.
- **Live checks** with MFA sign-in on the local stack, at 1280 px and 390 px (no horizontal scroll
  on any screen), on the demo scenario. They found and fixed:
  - tornado bars named by internal keys (`OPEX.PAYROLL`) instead of plain words (Payroll);
  - KPI values on the comparison shown unrounded (`0.11249…`) instead of 11.25%;
  - goal figures and working-capital days shown unformatted, and an empty loan list in a change's
    details;
  - the demo's hand-worked scenario figure: the demo year is seasonal, so the expected revenue
    change is 323,400.00, not 316,800.00 (the engine was right; the first hand figure assumed
    even months).

## Known limitations
- **The brief placed working capital on the Projections screen and scenarios as a column on Goals.**
  Working capital is its own screen (Cash & planning → Working capital), because it also starts
  from shared scenarios; goals against scenarios are a section under the selected goal. Say if you
  want them moved.
- **Scenario KPIs** show for the first year of the base only, and only once a scenario is shared.
  A base KPI that is not meaningful shows a dash without its reason.
- **What changed and why** reports six headline figures (revenue, EBITDA, net income, net cash flow,
  cash and debt at the end); line-level lineage is in the comparison and the API.
- **Sensitivity** cannot yet vary a single loan or the tax rate; one-variable results are shown as
  a table (the tornado has a chart and a table).
- **Greek wording** for all new screens and the Excel export needs a native speaker's review.
- Everything rests on the projection engine, which is **pending professional review** (#153).

## Decisions and approvals needed from you
1. **Review and merge** #183–#189 in order (each targets the previous; #183 targets `main`).
2. **ADRs to accept or change:** 0049 (scenario model), 0050 (scenario runs), 0051 (sensitivity and
   tornado), 0052 (KPI library 1.1 and projected KPIs).
3. **Defaults to confirm** (brief §3): at most 50 overrides per scenario and 3 scenarios per goal
   comparison; tornado ±10% by default and at most 25 drivers; quotas of 300 sensitivity runs a
   minute per user and 1,200 per workspace; DSCR over 12 months; scenario saved runs are never
   published.
4. **Still open:** the professional review of the projection engine (#153), the Cyprus tax rules
   verification (#154), and the Gate P items (#78), which you said you will answer later.

Milestone 8 waits for your review of this milestone and the Gate P answers.
