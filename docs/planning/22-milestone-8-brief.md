# 22 — Milestone 8 Implementation Brief: management report packs, dashboard v2, email alerts

Status: **APPROVED, IN PROGRESS.** No M8 code was written before approval, as for Milestone 7. The
product owner answered the proposed brief with "Continue" (2026-11-17), so the defaults in §3 and
the proposed answers in §7 are taken. Each can be changed at any time.

Backlog: [08 §Phase 3](08-implementation-backlog.md) (M8). Specification:
[10](10-cfo-fpa-specification.md) §7 (variance explanations), §9 (management reporting), §10
(dashboard) and §10.1 (nature encoding), approved 2026-11-03. Requirements:
[01](01-product-requirements.md) FR-M1 to FR-M3, FR-D1, FR-D2, FR-B4, FR-E3 and the dashboard
performance target. Testing: [12](12-fpa-testing-and-acceptance.md) §1 (golden budget variance
pack; final-pack immutability). Threats: [07](07-security-threat-model.md) T9 (formula injection),
T30 (pack scope). Epic: #83.

Starting point: the Milestone 7 stack (#183–#189) on `main`. Milestone 8 is the last milestone of
Phase 3. **Gate G** follows it: no external customer before the independent penetration test,
ASVS L2 sign-off, the legal documents, a disaster-recovery drill and a load test, all with your
approval. M8 itself needs no AWS resource: email is sent through the local mail catcher in
development, and the production sending service is a Gate P decision.

The projection engine is still **PENDING_PROFESSIONAL_REVIEW** (#153). Every pack section built on
projections or scenarios carries that notice, in the app and in every export.

## 1. Business purpose
Milestones 3 to 7 produce the numbers. Milestone 8 turns them into **the monthly management
pack**: the document a CFO sends to the owner or the board.
- **Report packs:** "Give me the March pack: overview, profitability, cash and the forecast,
  working capital, budget performance, KPIs, goals, risks and our commentary," as one document
  with frozen figures that still read the same in a year.
- **Review and sign-off:** a pack is prepared, reviewed by someone else, and finalised. A final
  pack can never change; a correction is a new version.
- **Excel and PDF:** each figure in the export equals the figure on screen, and every page says
  where the figures come from (ledger watermark, budget version, forecast run).
- **Dashboard v2:** arrange your own dashboard, add scenario comparison, waterfall and top
  variances, and save views (period and comparison).
- **Email alerts:** the in-app alerts of M4-7 also by email, immediately or as a daily digest,
  with each user choosing.

## 2. Rules carried from the approved specification
- **P5 (doc 10 §1):** a final pack is immutable (database trigger, tested as the runtime role).
  Changes create a new version that names the one it supersedes.
- **FR-E3 and doc 10 §9:** generating a pack freezes a **snapshot**: every figure, plus references
  to the calc runs, budget versions, assumption sets and ledger watermark used. The same snapshot
  always renders the same pack.
- **P1:** actuals come only from posted ledger entries, through `reporting`. Unposted drafts are
  excluded and shown as a count.
- **Doc 10 §7 and FR-B4:** variances above the threshold need an explanation from the line owner
  **before the pack can be finalised** (M4-3 explanations are reused).
- **FR-M3:** export values equal on-screen values exactly (tested). XLSX is formula-safe (T9) and
  has a nature column and legend. PDF has page numbers, a provenance footer and a **DRAFT**
  watermark until final.
- **T30:** a pack is generated under the generating user's permissions; its scope is stated on the
  cover page; every export is audited.
- **FR-D2 and §10.1:** actual, forecast and hypothetical stay visually distinct in packs, dashboard
  widgets and exports, never by colour alone.
- **Commentary is human-authored** (doc 10 §9). AI drafts come only in Phase 5, labelled.
- **Never invent regulations:** packs contain no tax or legal statements beyond what the existing,
  versioned rule data says, with its verification status.

## 3. Defaults proposed (you can change any of them)
| Question | Proposed default |
|---|---|
| Pack model (M8-1) | A **pack** belongs to one legal entity and one reporting period (a month, quarter or year). Lifecycle `DRAFT → IN_REVIEW → FINAL`, plus `SUPERSEDED`. The reviewer must not be the preparer (segregation of duties, as for entries). Packs are never deleted. |
| Snapshot (M8-1) | Generating a pack stores every figure it shows, as Decimal values with their nature, and references (calc run IDs, budget version, assumption set, ledger watermark). Regenerating a draft takes a new snapshot; a final pack keeps its snapshot for ever. |
| Templates (M8-2) | One built-in template with the ten sections of doc 10 §9, each switchable on or off per pack: executive overview, revenue and profitability, cash flow and projections, working capital, budget performance, KPI scorecard, forecast statements, risks, goal progress, commentary. Custom templates are left for later. |
| Comparison columns (M8-2) | Actual, budget (original and current), forecast, prior year, and the variances, for month, quarter-to-date, year-to-date and full-year outlook. The preparer chooses which columns appear. |
| Risks section (M8-2) | Written by people, like commentary (a short list of risks with owner and status). Nothing is generated. |
| Commentary (M8-2) | Plain text per section, attributed and versioned, at most 4,000 characters per section. No rich text. |
| Finalising (M8-1) | Refused while any variance above the threshold has no explanation, or while the period's figures have changed since the snapshot (an entry dated in or before the period was posted after it); each refusal says what to do. Entries for later months don't block (ADR-0053: "a referenced run is stale" would block every pack, because forecasts and KPI sets go stale on any posting). |
| Excel export (M8-3) | One sheet per section, values with number formats, a nature column and legend, formula-safe text, a cover sheet with scope and provenance. No formulas sheet in M8. |
| PDF export (M8-3) | ReportLab (already used for statement exports): A4, the workspace name and the pack title on each page (no logo in M8), page numbers, provenance footer ("Actuals as of {date}, ledger watermark {n}; Budget v{n}; Forecast run {id}"), a **DRAFT** watermark until final, charts as vector drawings with a table next to each. English or Greek. |
| Dashboard v2 (M8-4) | Users arrange widgets in a grid (order and width: full or half). New widgets: **scenario comparison** (a shared scenario against its base), **waterfall** (from budget to actual, or month to month), **top variances**. **Saved views**: a named period preset (MTD, QTD, YTD, LTM, custom) and comparison (budget, forecast, prior year) per user. A "today / cut-over" marker on every time chart. First load p95 < 1.5 s on the demo entity, measured. |
| Email alerts (M8-5) | Each user chooses per workspace: **immediately**, **daily digest** (08:00 Cyprus time) or **off**; the default is **off**, so nobody gets email they didn't ask for. Emails carry the alert's title, the entity name and a link, **but no amounts** (data minimisation; figures stay behind sign-in). An outbox table with retries; at most one immediate email per alert; an unsubscribe link in every email. English or Greek, as the user's language. Locally the mail catcher (Mailpit) receives them. |
| Charts | Stay as SVG drawn in React (as in M4 to M7). Apache ECharts (doc 10 §10) is left for the design change. |
| Personal workspaces | Packs and email alerts are for business and firm workspaces. Personal scenarios (left from M7) stay for later. |

## 4. Order and approach
One issue per item, in milestone M8 under epic #83.

| # | Item | Issue | Size | Approach |
|---|---|---|---|---|
| 1 | M8-1 Pack model, snapshot and review workflow | #190 | L | `mgmt_reporting` module: pack and pack-version tables (FORCE RLS, composite tenant keys, final packs immutable by trigger, never deleted), snapshot from `reporting`, `budgeting`, `projections`, `scenarios`, `kpi` and `goals` through their public interfaces, `DRAFT → IN_REVIEW → FINAL` with SoD, finalising checks, audit. |
| 2 | M8-2 Pack sections, comparison columns and commentary | #191 | L | The ten sections from the snapshot; comparison columns; human-written commentary and risks (versioned, attributed). Golden **budget variance pack** worked by hand (doc 12 §1). |
| 3 | M8-3 Excel and PDF export | #192 | M | XLSX and PDF from the same snapshot; provenance footer; DRAFT watermark; test that every exported value equals the API value. |
| 4 | M8-4 Dashboard v2 | #193 | M | Layout grid, three new widgets, saved views, cut-over marker, a performance test. |
| 5 | M8-5 Email alerts | #194 | M | Preferences, outbox with retries, immediate and digest sending, templates in English and Greek, unsubscribe, rate limits, audit; tested against the local mail catcher. |
| 6 | M8-6 Screens and the M8 report | #195 | L | Packs (list, generate, sections, commentary, review, finalise, export), dashboard editing, alert preferences; live checks at desktop and phone width; the Milestone 8 report. |

Every item follows the established patterns: tenant-owned models with FORCE row-level security
and composite keys; a permission on every route (existing `reports.*`, `planning.*` and
`dashboard.*` permissions, plus `reports.finalise` for finalising a pack); an audit event for each
change; problem+json errors and Decimal money; OpenAPI regenerated; import contracts (planning and
reporting modules never import the ledger); English and Greek; one PR per issue, each stacked on the
previous one; PROGRESS and pr-links updated; no deployment and no migration on any deployed
environment.

## 5. Acceptance criteria
- **AC-MR1** Generating a pack freezes every figure and the references it used. Rendering the same
  snapshot twice gives identical content (hash), and a posting after generation does not change it.
- **AC-MR2** A final pack cannot be changed or deleted (database tests as the runtime role). A
  correction is a new version naming the one it supersedes.
- **AC-MR3** The reviewer cannot be the preparer. Finalising is refused, with a reason, while a
  variance above the threshold lacks an explanation, or while the period's figures have changed
  since the snapshot (ADR-0053). Entries for later months do not block it.
- **AC-MR4** The golden budget variance pack matches a hand-worked example to the cent, including
  favourable and unfavourable directions and the comparison columns.
- **AC-MR5** Every value in the Excel and PDF exports equals the API value for the same snapshot
  (tested cell by cell and line by line). Exports are formula-safe, carry the provenance footer and
  the nature of each figure, show DRAFT until final, and are audited.
- **AC-MR6** A pack generated by a user contains only data that user may see; the cover page states
  the scope (T30).
- **AC-DB2** Dashboard layouts, saved views and the new widgets work per user with a workspace
  default; every widget shows nature by more than colour and has a table alternative; first load
  p95 < 1.5 s on the demo entity, measured.
- **AC-EM1** An alert produces at most one immediate email per subscribed user; a digest gathers
  the day's alerts; users who chose "off" get nothing; emails contain no amounts and have a
  working unsubscribe link; failures are retried and recorded.
- **AC-UI3** Every new screen passes axe, has no horizontal scroll at phone width, and works in
  English and Greek.
- **Quality gates (doc 12 §4.8):** domain coverage ≥ 90%, calculation code 100% branch, all CI
  gates green.

## 6. Risks
| Risk | Mitigation |
|---|---|
| A pack sent outside the company with more than the sender should see (T30) | Generation under the user's permissions; scope on the cover page; export audit; tests |
| A final pack that silently changes | Snapshot of every figure; trigger-enforced immutability; hash test |
| Figures in Excel or PDF that differ from the screen | One snapshot feeds the screen and both exports; cell-by-cell equality tests |
| Email leaking financial data, or annoying users | No amounts in emails; default off; unsubscribe link; rate limits |
| Projections in a pack read as validated | The pending-review notice on every projection and scenario section, in the app and in exports |
| Scope (three L items) | One PR per issue in the order above; each PR stands alone |

## 7. Decisions (taken as proposed on 2026-11-17; change any of them at any time)
| # | Question | Taken for now |
|---|---|---|
| 1 | Approve this brief and its defaults (§3)? | Approved: "Continue" |
| 2 | Branding on PDF packs: the workspace name only (proposed), or an uploaded logo and colours? | Name only in M8 |
| 3 | Email alerts: default **off** until each user turns them on (proposed), or **daily digest** by default for owners? | Off |
| 4 | Should emails show amounts (for example "Cash forecast below minimum by €12,400")? Proposed: no, only the title and a link, so figures stay behind sign-in. | No amounts |
| 5 | Who may finalise a pack: owners and finance managers (a new `reports.finalise` permission for those roles), with a reviewer who is not the preparer? | Yes |
| 6 | Production email service (needed only when the pilot goes online; part of Gate P): Amazon SES in the pilot account, or another provider? | SES, decided at Gate P |
