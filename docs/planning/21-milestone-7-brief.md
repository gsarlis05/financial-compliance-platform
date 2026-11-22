# 21 — Milestone 7 Implementation Brief: scenarios, sensitivity, working capital, advanced KPIs

Status: **APPROVED, IN PROGRESS.** The product owner's instruction of 2026-11-16 was that no M7
code be written before approval. They answered the brief with "Continue as you think it's better",
so the defaults in §3 and the proposed answers in §7 are taken. Each can be changed at any time.

Backlog: [08 §Phase 3](08-implementation-backlog.md) (M7). Specification:
[10](10-cfo-fpa-specification.md) §3.6, §5.1, §6.2 item 9, §8 and §10.1 (approved 2026-11-03).
Requirements: [01](01-product-requirements.md) FR-C6, FR-G2, FR-S1 to FR-S3, and the performance
targets. Architecture: [02](02-software-architecture.md) (`scenarios` module) and
[03](03-entity-relationship-model.md) (`SCENARIO`, `SCENARIO_OVERRIDE`, calc-run kinds `SCENARIO` and
`SENSITIVITY`). Testing: [12](12-fpa-testing-and-acceptance.md) §1. Threats:
[07](07-security-threat-model.md) T31 and T34. Epic: #82.

Starting point: `main` at the end of the repository consolidation (2026-11-16), with M0 to M6 and
the M6 follow-up merged. The projection engine (M6-3, engine version 3) is still
**PENDING_PROFESSIONAL_REVIEW** (#153). Everything in M7 is built on that engine and inherits its
status. Nothing in M7 says or implies that the projections are validated or certified.

## 1. Business purpose
Milestones 3 to 6 answer "what has happened?", "what is likely to happen?" and "are we on plan?".
Milestone 7 answers **"what if?"** and **"what matters most?"**:
- **Scenarios:** "What happens to cash, profit and the balance sheet if revenue falls 15%, we hire
  two people from March and take a €200k loan?" Each scenario is compared with its base, line by
  line, and every changed figure says which assumption changed it.
- **Sensitivity and tornado:** "Which assumptions move our minimum cash, or our year-end profit,
  the most?" One assumption at a time, ranked.
- **Working capital:** "How much cash is tied up in receivables, stock and payables over the next
  12 to 24 months, and what is it worth to collect 10 days faster?"
- **Goals against scenarios:** "Do we still reach the 20% EBITDA margin goal under the downside
  scenario?" Shown side by side with the base.
- **Advanced KPIs:** net debt to EBITDA, debt service cover (DSCR), receivables and inventory
  turnover, and KPIs on projected and scenario figures.

## 2. Rules carried from the approved specification
- **Scenarios are always hypothetical (doc 10 §8, FR-S3).** Every scenario value has nature
  `HYPOTHETICAL`. A scenario never changes a budget, an assumption set, a forecast or the books.
  Promoting a scenario is an explicit action that creates a **draft** assumption set, which then
  goes through the normal approval (M6-2).
- **Typed overrides only.** Each override is a validated object of one of the eight types in doc 10
  §8. There is no free-form formula or code.
- **P1:** actuals come only from the ledger through `reporting`.
- **P4:** a scenario run is a calculation run. The same base, overrides and engine version give the
  same output hash.
- **P6 and FR-S2:** lineage on every changed output lists the override IDs that changed it, and
  there is a "what changed and why" table.
- **P7 and §2.4:** Decimal throughout, with rounding per line. The scenario's statements must pass
  the same eight invariants as any projection. A scenario that breaks one is `INVALID`.
- **Sensitivity (§3.6, doc 02):** N deterministic re-runs with overrides. They are cached by input
  hash and **not** stored as official versions.
- **Nature encoding (§10.1):** hypothetical figures use a dotted line, a distinct hue and the
  scenario's name in the legend. Colour is never the only encoding, and every chart has a table
  alternative.
- **Threat T34:** quotas per user and tenant, time limits and input-hash caching for scenario and
  sensitivity runs.
- **Never invent regulations:** the new-hire override's employer social-insurance percentage must
  be a **verified parameter** (doc 10 §8). No rate is built in (see §3 and §7).

## 3. Defaults proposed (you can change any of them)
As in Milestones 5 and 6, the simplest sound option is proposed wherever the specification leaves a
choice (owner, 2026-11-10: "continue with what is easier for now for best coding").

| Question | Proposed default |
|---|---|
| Scenario base (M7-1) | An **approved assumption set** (the M6 projection model) of one legal entity. A scenario pins its base version. A newer approved version doesn't change the scenario; it shows "a newer base exists" and can be rebased by copying the overrides into a new scenario. Budgets are reached through "start from the approved budget" (M6-2), so a separate budget base isn't needed. |
| Scenario lifecycle (M7-1) | `DRAFT → SHARED → ARCHIVED` (doc 03). A draft is visible only to its author. A shared scenario is visible to anyone with `planning.read` on the entity and can't be edited, only copied. Archived scenarios are kept and never deleted. |
| Override types (M7-1) | All eight of doc 10 §8, applied in their stated order: **percent change** and **absolute change** on revenue or cost lines (with start and end months); **timing shift** (days added to DSO or DPO for a line, or a month shift of a revenue or cost line); **new financing** (a loan with the M6F-4 structures); **new hire** (department, gross monthly salary, start month, and the employer cost % entered by the user with its source; see §7); **capex** (amount, month, useful life, funding: cash or a new loan); **one-off cash event** (amount, month, treated as an expense or as settling a liability); **rate change** (percentage points on the named loans or the facility, from a month). |
| 13-week cash scenarios | The existing what-ifs (M3-9: timing shift, percent change, one-off) stay as the 13-week tool. A scenario can also be shown against the latest 13-week forecast when **all** its overrides have a 13-week meaning. Otherwise the screen says which overrides don't apply to the 13-week view. |
| Outputs compared (M7-2) | Base and scenario side by side, with the difference, by month, quarter and year: the three statements, minimum cash and first shortfall, KPIs (the library on projected figures), debt (balance, interest, DSCR) and a short stability summary (months below minimum cash, peak facility use, lowest DSCR). Plus a "what changed and why" table: each override, the lines it changed and by how much. |
| Storage (M7-1, M7-2) | Scenarios and overrides are tenant tables with FORCE RLS. A scenario **run** is a stored calc run (kind `SCENARIO`) only when the user saves it. Unsaved runs are computed in memory, as M3-9 what-ifs are. |
| Promote (M7-2) | "Create an assumption-set draft from this scenario" copies the base set's values with the overrides applied, records the scenario ID as its origin, and needs `planning.run`. Approval is the normal M6-2 step with `planning.publish`. |
| Sensitivity (M7-3) | **One variable:** a driver is varied over a stated range in up to 11 steps (for example revenue −20% to +20%, or DSO +0 to +60 days), showing the chosen output at each step. **Tornado:** each driver is shocked by ±X% (default 10%) on its own, and drivers are ranked by the swing in the chosen output. **Outputs:** minimum cash, first shortfall month, closing cash, EBITDA or net income for a chosen year. **Drivers:** revenue lines, gross margin, operating cost lines, DSO, DIO, DPO, interest rate, capex. The base is an approved set or a shared scenario. Runs are cached by input hash (kind `SENSITIVITY`) and not stored as versions. At most 25 drivers × 2 shocks per tornado. |
| Working capital (M7-4) | A working-capital view of any projection or scenario: receivables, inventory and payables by month, net working capital, its month-on-month cash effect, and DSO, DIO, DPO and the cash conversion cycle as projected. Plus "what is N days worth?": the cash released by collecting N days faster (or paying N days later), computed by the engine, not estimated. "Start from actuals" (M6-2) already sets the days from the trailing 12 months, and the view shows those observed days next to the projected ones. Days by customer group are left for later. |
| Goals against scenarios (M7-5) | A goal evaluation can name a shared scenario. Its likely outcome is then taken from the scenario run, with method `SCENARIO` and nature `HYPOTHETICAL`. The goal screen shows the base and up to three scenarios side by side: likely outcome, gap and status. A goal itself never changes. |
| Advanced KPIs (M7-6) | Library version **CORE@1.1**, adding net debt / EBITDA (LTM), DSCR ((EBITDA − cash taxes) / (principal + interest due), over 12 months by default), receivables turnover and inventory turnover. ROA and ROE already exist (M4-4). KPI values for **projected** and **scenario** months use the same definitions, with nature `FORECAST` or `HYPOTHETICAL`. Older KPI sets keep their CORE@1.0 values. |
| Screens (M7-7) | **Scenarios:** list, builder (override forms with plain-words validation), comparison (statements, cash chart with dotted scenario lines, the "what changed" table). **Sensitivity:** setup, one-variable table and chart, tornado (SVG bars with a table alternative). Plus a working-capital panel on Projections and a scenario column on Goals. English and Greek. Excel export of a comparison with a nature row, formula-safe as in M4-2 and M6-6. |
| Personal workspaces | Scenarios on personal projections (salary change, new loan, large purchase; doc 10 §11) are **not** in M7. They can follow in M8 or later. |

## 4. Order and approach
One issue per item, in milestone M7 under epic #82.

| # | Item | Issue | Size | Approach |
|---|---|---|---|---|
| 1 | M7-1 Scenario model and overrides | #176 | M | `scenarios` module: scenario and override tables (FORCE RLS, composite tenant keys, draft-only edits by trigger, never deleted), the eight typed overrides with validation, lifecycle, API, audit. |
| 2 | M7-2 Scenario runs and comparison | #177 | L | Overrides are applied to a copy of the base inputs in their stated order. The M6 engine runs unchanged (eight invariants). The result is labelled `HYPOTHETICAL`, with lineage by override ID. Comparison with the base; "what changed and why"; save as a run; promote to a draft assumption set. Property test: **a scenario with no overrides equals its base**, hash for hash (doc 12 §1). |
| 3 | M7-3 Sensitivity and tornado | #178 | M | Deterministic re-runs in memory with cache by input hash, quotas and a time limit (T34); one-variable and tornado endpoints; performance test (doc 01: scenario re-run < 3 s). |
| 4 | M7-4 Working-capital forecasting | #179 | S | A view over projection and scenario runs, the "N days worth" calculation through the engine, and observed vs projected days. |
| 5 | M7-5 Goals against scenarios | #180 | S | Goal evaluation with a named scenario (`GOAL_EVAL` v3); side-by-side view. |
| 6 | M7-6 Advanced KPIs | #181 | M | CORE@1.1 definitions with worked examples; LTM EBITDA and scheduled principal from the registers or loans; KPIs on projected and scenario months. |
| 7 | M7-7 Scenario and sensitivity screens | #182 | L | Screens, charts with the hypothetical encoding, Excel export, live checks at desktop and phone width. |
| 8 | M7 report (with M7-7) | #182 | — | Evidence for each acceptance criterion, and owner items. |

Every item follows the established patterns:
- tenant-owned models with FORCE row-level security and composite keys;
- a permission on every route (`planning.read`, `planning.run`, `planning.publish`; no new roles);
- an audit event for each change;
- problem+json errors and Decimal money;
- OpenAPI regenerated;
- import contracts (planning modules never import the ledger; `scenarios` uses `projections`,
  `cashflow`, `goals` and `kpi` only through their public interfaces);
- English and Greek;
- one PR per issue, each stacked on the previous one;
- PROGRESS and pr-links updated;
- no deployment and no migration on any deployed environment.

## 5. Acceptance criteria
- **AC-SC1** All eight override types validate their parameters and say what is wrong in plain
  words. An override outside the base's horizon is refused.
- **AC-SC2** A scenario with no overrides gives exactly the base's results and output hash
  (property test over random approved sets).
- **AC-SC3** For any scenario (property test) every month satisfies the eight projection
  invariants exactly. A scenario that fails one is `INVALID` and says where.
- **AC-SC4** Every scenario value is `HYPOTHETICAL` in the API, the screens and the export. Every
  changed figure lists the overrides that changed it. The "what changed and why" table sums to the
  total difference.
- **AC-SC5** A scenario never changes its base or any approved or published object (database tests
  as the runtime role). Promoting creates a draft only, which needs the normal approval.
- **AC-SC6** Reproducibility: the same base, overrides and engine version give the same hash, and
  new postings don't change a saved scenario run.
- **AC-SE1** One-variable sensitivity and tornado results equal individual engine runs with the
  same single override. The tornado ranks by absolute swing, and ties are ordered by driver name.
- **AC-SE2** Quotas, time limit and caching hold (repeated requests are served from the cache; the
  quota is refused with a clear message). A sensitivity run with 25 drivers on a 24-month horizon
  completes within the performance target, or the gap is reported as a known limitation.
- **AC-WC1** Working-capital balances and the cash conversion cycle in the view equal the
  projection's balance sheet. "N days worth" equals the difference between two engine runs.
- **AC-GS1** A goal evaluated against a scenario uses the scenario's figures, says so, and is
  shown next to the base. The goal itself is unchanged.
- **AC-KP6** Each new KPI matches a hand-worked example. It is "not meaningful" where defined
  (EBITDA ≤ 0 for net debt / EBITDA; no debt service for DSCR). Older KPI sets are unchanged.
- **AC-UI2** Every new screen passes axe, shows hypothetical figures by more than colour (dotted
  lines and labels), and has a table alternative to each chart. No horizontal scroll at phone
  width.
- **Quality gates (doc 12 §4.8):** domain coverage ≥ 90%, calculation engines 100% branch, all CI
  gates green.

## 6. Risks
| Risk | Mitigation |
|---|---|
| A scenario read as a forecast or as actual | `HYPOTHETICAL` on every value, dotted encoding, the scenario name on every chart and export, never shown in the outlook or used by goals unless named |
| Overrides that interact in surprising ways | A fixed, documented order of application; lineage per override; the "what changed and why" table; the no-override property test |
| Expensive runs (T34) | Cache by input hash, quotas per user and tenant, a time limit, at most 25 drivers per tornado |
| An unverified statutory rate entering a scenario | No built-in social-insurance or tax rate: the user enters it with a source, and screens and exports label it "entered by user, not verified" |
| Results taken as professional advice | Projections, scenarios and sensitivities carry the existing notice that the engine is pending professional review; nothing is called validated |
| Scope (two L items) | One PR per issue in the order above; each PR stands alone |

## 7. Decisions (taken as proposed on 2026-11-16; change any of them at any time)
| # | Question | Taken for now |
|---|---|---|
| 1 | Approve this brief and its defaults (§3) | Approved: "Continue as you think it's better" |
| 2 | New-hire employer costs: should the platform hold **verified** Cyprus social-insurance and related contribution rates as versioned data (like the tax rules, verified by a professional, #93/#154), or should the user enter the employer cost % per override with a source? | The user enters it; nothing is built in |
| 3 | Scenario base: approved assumption sets only (proposed), or also budget versions and 13-week forecasts as separate bases? | Approved assumption sets only |
| 4 | Personal-workspace scenarios (salary change, new loan, large purchase) in M7 or later? | Later (M8 or after) |
| 5 | Charts: keep SVG drawn in React (as in M4 and M6), or move to Apache ECharts (doc 10 §10) now? | Keep SVG; revisit with the design change |
