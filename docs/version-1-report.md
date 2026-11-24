# Version 1 report: the complete platform for the owner's own use

Status: **complete except the dependency updates (V1-5, #211)**. It awaits your review. Brief:
[planning doc 24](planning/24-version-1-brief.md), approved 2026-11-22.

**Nothing was created on AWS. No migration was applied anywhere but local development and CI.
No real data was used, and nothing is ever filed with the Tax Department.** The projection engine
stays **pending independent professional review** (#153). Every VAT code, box rule and rate stays
**pending verification by a Cyprus tax professional** (#93); your list for that review is
[docs/review/professional-review-list.md](review/professional-review-list.md).

## What you can do now
On top of Milestones 1 to 8, you can:
- **Work alone:** in a one-person workspace you approve your own entries, unlocks, budgets, KPIs,
  packs and VAT returns. Each self-approval is recorded and shown (V1-1).
- **Run it on your own computer:** one command to install, start, stop, back up, restore and
  upgrade, with MFA sign-in on the local identity provider
  ([guide](user-guide/install-on-your-computer.md), V1-3).
- **Prepare the Cyprus VAT return** from the posted books (V1-2):
  - the 13 boxes, each with its lines, source and rule version;
  - checks and adjustments;
  - four steps: draft, reviewed, finalised, filed;
  - schedules and a reconciliation to the VAT accounts;
  - import records and VIES statements;
  - PDF, Excel and CSV.

  You file it yourself on the portal ([guide](user-guide/vat.md)).
- **Record purchases and sales in other currencies** at the rate of the transaction's date and
  time, with its source (V1-2h). **Revalue foreign balances and clear settled ones** with prepared
  exchange-difference entries (V1-2h2).
- **Enter data faster:**
  - a searchable VAT code list with your favourites first;
  - each account's usual code offered;
  - suggestions from what you typed before (V1-2i).
- **See the fixed-asset register against the ledger** on any date: cost and accumulated
  depreciation per account, and depreciation prepared but not posted (V1-4).

## The end-to-end check (V1-4, #210; AC-V2)
**A full synthetic year was walked through every module, and the numbers agree from screen to
screen.**

1. **Through the API the screens use** (`make demo`; `tests/devtools/test_demo.py`):
   - The demo runs through every module:
     - the year's books, bank statement, documents and year-end close;
     - budget, goals and alerts, dashboard, personal books, engagement;
     - fixed assets, assumptions, projection, outlook, rolling forecast and scenario;
     - the December report pack and the first quarter's VAT return;
     - the full export.
   - It ends with **20 agreement checks**; any disagreement stops it and names both figures.

| From | To | What must agree |
|---|---|---|
| Ledger | Trial balance | Debits = credits |
| Statements | Statements | Cash in the balance sheet = closing cash in the cash flow; assets = equity and liabilities; profit = profit in equity |
| Statements | Budget variance | The prior-year column's sales = sales in the statements; the budget column = the approved budget |
| Statements | KPIs | Gross margin, EBITDA margin and current ratio recomputed from the statements |
| Ledger | Cash forecast | Opening cash = cash in the balance sheet |
| Ledger | Fixed assets | Cost and accumulated depreciation per account, register = ledger |
| Ledger | Projection | Its opening balance sheet is actual and its cash is the books'; the first month starts from it |
| Statements | Report pack | Total assets and cash = the balance sheet; the KPI section is filled |
| VAT accounts | VAT return | Each bridge from boxes to ledger has nothing unexplained |

2. **In a real browser** (`make e2e-walkthrough`, with `make services`, `run-backend` and
   `run-frontend` running):
   - The walk resets a local test user, signs in through Keycloak with MFA, and loads the demo
     year shared with that user.
   - It opens, in order, nine screens:
     - trial balance;
     - profit and loss;
     - balance sheet;
     - cash forecast;
     - dashboard KPIs;
     - fixed assets (register and ledger);
     - projection;
     - the December report pack;
     - the first quarter's VAT return.
   - On each screen it checks that the visible figures are the ones the demo's checks agreed on:
     cash 371,514.38 on the trial balance, balance sheet, cash forecast, projection and pack;
     profit 89,973.47; total assets 700,545.98; gross margin 45.00%. It keeps a screenshot of
     each screen.
   - Result on 2026-11-23: **all nine screens passed.**

### Found and fixed
| Finding | Fix |
|---|---|
| A report pack had **no KPIs** unless someone had opened the dashboard for exactly that period first | Generating a pack calculates its KPI set (a stored, reproducible run); a preparer who may not run calculations is told why |
| The **fixed-asset register was never checked against the ledger**, and the demo's van and laptops were in the register but never booked | A register-and-ledger reconciliation (API and screen); the demo books the purchase |
| The **projections screen opened on the latest run**, a rolling forecast, not on the published projection the outlook and packs use | It opens on the published projection |
| A zero ledger balance in the new reconciliation printed as **"-0.00"** | Zero is shown as 0.00 |
| Export tests compared every figure as an exact amount, which a long KPI ratio is not | Amounts compared exactly; ratios to the cent in the PDF and to float precision in Excel |
| The demo shared its workspace with the **oldest account** of an email (a reset test user signs in as a new account) | It picks the account that signed in last |

## Items
| Item | PR | What |
|---|---|---|
| V1 brief | #206 | Planning doc 24 and issues #207–#211 |
| V1-1 One-person workspace | #212 | Self-approval, recorded and allowed by the database only for one member (ADR-0055) |
| V1-2a VAT report | #221 | VAT periods, the report from posted lines, settlement draft (ADR-0056) |
| V1-3 On your computer | #222 | Install, start, stop, back up, restore, upgrade; MFA; guide (ADR-0057) |
| V1-2b to V1-2g VAT | #223–#228 | Codes and line details; 13 boxes; four steps; schedules and exports; imports; VIES (ADR-0058 to ADR-0063) |
| Review list | #229 | The professional review list, generated from the platform's data |
| V1-2h Foreign currency | #232 | Lines at the transaction's rate with its source (ADR-0064) |
| V1-2i Data entry | #233 | VAT code picker with favourites, typing suggestions (ADR-0065) |
| V1-2h2 Exchange differences | #234 | Revaluation and realised differences as drafts (ADR-0066) |
| V1-4 End-to-end check | #235 | The 20 agreement checks, the browser walk-through, the fixes above, this report |
| V1-5 Dependencies | — | Next: the 16 dependency-update PRs (#211) |

## Acceptance (brief §4)
| Criterion | Evidence |
|---|---|
| **AC-V1** Each item meets its "done" column, with tests, all gates green and PROGRESS updated | The PRs above, each merged with every CI check green; [PROGRESS](PROGRESS.md) |
| **AC-V2** The end-to-end walk-through passes from a clean install | The demo's 20 checks (`test_demo_walkthrough_runs_end_to_end`, every CI run) and `make e2e-walkthrough` in a browser against a fresh demo workspace; the clean install itself was verified in V1-3 (#222) |
| **AC-V3** Every VAT box says where its definition comes from and that it awaits verification | The return shows each box's source and rule version, marked unverified (V1-2c); `docs/vat/coverage.md` |

## Known limitations
- The browser walk-through runs on a developer machine with the local services. It is not part
  of CI, because CI has no identity provider for MFA sign-in.
- The demo shows the two-person flow (an accountant prepares, a reviewer approves), not the
  one-person setting.
- The Tax Department's XML file for the return is deferred by your decision (#220).
- Tax rules, VAT rules and the projection engine await professional review (#93, #153).

## Decisions and approvals needed from you
1. Review this report and the walk-through's screenshots (run `make e2e-walkthrough` yourself;
   the screenshots are listed at the end).
2. Go through the [professional review list](review/professional-review-list.md) with a Cyprus
   tax professional when you can.
3. V1-5 (dependency updates) is next; after it, version 1 is complete.
