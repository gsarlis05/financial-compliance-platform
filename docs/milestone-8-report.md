# Milestone 8 report: management report packs, dashboard v2, email alerts

Status: **complete, awaiting product owner review** (PRs #196–#202, stacked on the Milestone 7
stack; each is reviewable on its own). **No environment exists beyond local development and CI.
Nothing was created on AWS, no email service was set up, and no migration has been applied
anywhere else.** Brief: [planning doc 22](planning/22-milestone-8-brief.md), approved 2026-11-17
("Continue"), so its defaults in §3 and the proposed answers in §7 were taken.

Milestone 8 is the last milestone of Phase 3. **Gate G comes next**: no external customer before
the independent penetration test, the ASVS L2 sign-off, the legal documents, a disaster-recovery
drill and a load test, all with your approval.

The projection engine is still **pending independent professional review** (#153); every pack
section and dashboard widget built on projections or scenarios says so.

## What you can do now
On top of Milestones 1 to 7, you can:
- **Produce the monthly management pack** (Reports → Report packs) for a month, quarter or year:
  executive overview, revenue and profitability, cash flow with the 13-week forecast, financial
  position and working capital, budget performance (actual against the budget, the original budget
  and the prior year, with variances and their explanations), KPI scorecard, forecast, risks, goal
  progress and commentary. **Its figures are frozen** when you generate it.
- **Review and sign it off:** the preparer submits it; a reviewer (owner, partner or finance
  manager) returns it with a note or finalises it, never their own. A pack is refused while a
  variance above the thresholds has no explanation, or while entries in its period were posted
  after it was made. A final pack never changes; a correction is a new version.
- **Write commentary and keep a risk list** (owner, status, mitigation) in the pack.
- **Export it to Excel or PDF**, in English or Greek, with where every figure comes from and DRAFT
  on every page until it is final.
- **Arrange your dashboard:** half or full width per widget, a **waterfall** from the budgeted to
  the actual result, a **scenario comparison** widget, the **last twelve months** as a period, and
  **saved views** (a period and a comparison under a name).
- **Get alerts by email**, immediately or as a daily digest: titles and links only, never amounts;
  off unless you choose; one click stops them.

Try it with `make demo` ([demo script](demo.md)); its 35 steps now include the December 2026 pack,
prepared by the accountant and finalised by the owner. User guides:
[report packs](user-guide/report-packs.md), [dashboard](user-guide/dashboard.md) and
[alerts](user-guide/alerts.md).

## Items
| Item | PR | What |
|---|---|---|
| M8 brief | #196 | Planning doc 22 and issues #190–#195 |
| M8-1 Report packs | #197 | `mgmt_reporting` module: frozen snapshot under the preparer's permissions, `DRAFT → IN_REVIEW → FINAL`, reviewer ≠ preparer, finalising checks, new versions (ADR-0053) |
| M8-2 Sections | #198 | The ten sections from the snapshot, comparison columns, human commentary and risks; golden budget variance pack |
| M8-3 Exports | #199 | Excel and PDF from the same sections; provenance footer, DRAFT watermark, formula-safe, audited |
| M8-4 Dashboard v2 | #200 | Widths, waterfall and scenario widgets, LTM preset, saved views, only shown widgets built |
| M8-5 Email alerts | #201 | Preferences, outbox with retries and an hourly limit, digests, one-click unsubscribe, scheduled sender (ADR-0054) |
| M8-6 Screens | #202 | Report packs page, dashboard v2 controls, email preference; demo step; this report |

## Acceptance criteria (brief §5)
| Criterion | Evidence |
|---|---|
| **AC-MR1** A pack freezes every figure and reference; the same snapshot renders identically; later postings don't change it | `tests/mgmt_reporting/test_packs.py::test_a_pack_freezes_its_figures` (a posting dated in the period leaves snapshot and hash unchanged; regenerating a draft takes the figures again) |
| **AC-MR2** A final pack cannot be changed or deleted; a correction is a new version | `test_new_versions_and_the_database` (database refuses updates, period changes, deletion, a final insert and a wrong supersedes; v2 supersedes v1) |
| **AC-MR3** Reviewer ≠ preparer; finalising refused, with a reason, for missing explanations or changed period figures | `test_review_and_finalise` (403 for the preparer; 409 naming `REV.SALES (MONTH)`; 409 after a March posting; an April posting does not block); database refuses the preparer as reviewer. "A referenced run is stale" became "the period's figures changed" (ADR-0053: forecasts go stale on any posting) |
| **AC-MR4** Golden budget variance pack to the cent | `tests/mgmt_reporting/test_sections.py::test_golden_budget_variance_pack` (hand-worked tables in the docstring: March sales 0 against 1,000, −1,000, −100.00%, unfavourable; year to date −2,000, −66.67%, prior year 800) |
| **AC-MR5** Exports equal the API; formula-safe; provenance; DRAFT; audited | `tests/mgmt_reporting/test_exports.py` (every Excel value cell by cell, over 100 cells; PDF lines through `pdf_lines`, the one function that writes them; Greek number format; `'=…` and `'+…` neutralised; DRAFT and final file names; audit events) |
| **AC-MR6** A pack holds only what its preparer may see; scope stated | `snapshot._block` stores `denied` blocks without data; scope line on the Excel cover and the PDF cover; `test_permissions_and_scope` |
| **AC-DB2** Layouts, views and new widgets per user; nature by more than colour; p95 < 1.5 s | `tests/dashboards/test_dashboard_v2.py` (waterfall by hand: 750 − 2,000 + 1,200 + 200 + 100 = 250; scenario totals equal its comparison; saved views personal; p95 < 1.5 s with every widget except the scenario); `src/m8.test.tsx` (labels and natures in words) |
| **AC-EM1** One immediate email per alert and user; digest; off means nothing; no amounts; unsubscribe; retries recorded | `tests/dashboards/test_alert_emails.py` (5 tests: once per alert; details with amounts never in the body; anonymous unsubscribe; audience respected; digest at 08:00 Cyprus time and once a day; retries at 2, 4, 8, 16 minutes then FAILED; hourly limit; the job finds workspaces through its narrow function) |
| **AC-UI3** axe, phone width, English and Greek | `src/m8.test.tsx` (4 tests with axe, no violations); live checks at 1280 px and 390 px |

## Database changes (Milestone 8)
| Module | Migrations | Content |
|---|---|---|
| mgmt_reporting | 0001–0004 | report packs (lifecycle trigger: starts as draft, fixed identity, frozen in review, reviewer ≠ preparer, final only to superseded, never deleted; one open version per pack); commentary and risks (append-only, draft-only) |
| dashboards | 0005–0008 | saved views; alert email preferences and outbox; `dashboards_alert_email_tenant_ids()` and `dashboards_alert_email_unsubscribe(token)` (narrow SECURITY DEFINER functions) |

Every new tenant table has FORCE row-level security and composite tenant keys. Applied locally only.

## Security controls added
- **A pack never holds more than its preparer may see** (T30), and it says so on its cover.
- **Segregation of duties** on packs in the service and the database; every step audited.
- **Exports** are formula-safe (T9), need the export permission and are audited with the snapshot
  hash.
- **Emails carry no amounts or details**, only titles and links; they are off by default; one
  click stops them without signing in, through a function that reveals nothing else.
- **No AWS resource and no real email**: development sends to the local Mailpit catcher.

## Quality
QUALITY_PLACEHOLDER

## Known limitations
- **Packs:** one built-in template; no logo or colours on the PDF (brief §7 item 2); charts appear
  as tables in the PDF. Explanations added after generation need the pack returned to draft and
  regenerated.
- **Dashboard:** no custom date range yet; the scenario widget summarises the whole horizon.
- **Email:** no bounce handling yet (comes with the production service, Gate P); more than 20
  alerts an hour per user stay in the app only.
- **Greek wording** for the new screens, exports and emails needs a native speaker's review.

## Decisions and approvals needed from you
1. **Review and merge** #183–#189 (Milestone 7), then #196–#202 (Milestone 8), in order.
2. **ADRs to accept or change:** 0053 (report packs) and 0054 (alert emails).
3. **Gate P:** the production email service (brief §7 item 6), with the other Gate P items.
4. **Gate G** (before any external customer): penetration test and its provider, ASVS L2 sign-off,
   legal documents (data processing agreement, record of processing, sub-processors, terms),
   disaster-recovery drill, load test, status page.
5. Still open: #153 (professional review of the projection engine), #154 (Cyprus tax rules).
