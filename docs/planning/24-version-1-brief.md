# 24 — Version 1 Brief: a complete platform for the owner's own use

Status: **APPROVED (2026-11-22).** The product owner asked for "a version 1 that only I am going
to use", finished end to end, with every part working together, and answered four questions:

| Question | Owner's answer |
|---|---|
| Where version 1 runs | On the owner's own computer first; AWS later, as a separate step (Gate P) |
| Merging | The developer merges each PR, in order, once its checks pass |
| Steps that need a second person | The owner may approve their own work; every such approval is recorded |
| Scope | Everything built so far, finished and working together, **plus Cyprus VAT return preparation** |

Gate G (external customers) is **not needed** for version 1: nobody but the owner uses it. The
Gate G brief (`23-gate-g-brief.md`) is kept for later and marked deferred.

## 1. What version 1 is
- One person, one computer, synthetic data until the owner starts entering their own books.
- Everything from Milestones 1 to 8: ledger, bank import and reconciliation, documents,
  statements, budgets and variance, KPIs, goals and alerts, cash forecast, fixed assets,
  projections, scenarios and sensitivity, report packs, dashboards, personal finances.
- Cyprus VAT return **preparation**: the boxes computed from the posted ledger, checked and
  signed off by the owner, exported, and then filed by the owner on the Tax Department's
  portal. The platform **never files a return** and never calls itself a tax adviser.

## 2. Rules that do not change
- Money is `Decimal`; posted entries never change; double entry always balances.
- Tax rules are versioned data with their source. **No rule, rate or box is invented**: every
  VAT box definition comes from the official form and its notes, and stays marked
  `PENDING_PROFESSIONAL_VERIFICATION` until a Cyprus tax professional confirms it (#93).
- The projection engine stays `PENDING_PROFESSIONAL_REVIEW` (#153).
- No AWS resource is created; no real data leaves the owner's computer.

## 3. Work, in order (one issue and one PR each)
| # | Item | What "done" means |
|---|---|---|
| V1-1 | **One-person workspace** | A workspace setting, on only while the workspace has exactly one member. When on, the person who prepared something may also approve it: journal entries, period unlocks (one approval instead of two), budgets, workspace KPIs, report packs and VAT returns. Each such approval is stored as **self-approved**, shown on screen and in exports, and audited. The database rules accept a self-approval only in a one-person workspace. Inviting a second person is refused until the setting is turned off. |
| V1-2 | **Cyprus VAT return preparation** | VAT periods per entity; the boxes of the official return computed from posted lines by VAT code, with a drill-down from every box to its lines; reasoned adjustments; checks (output VAT agrees with the VAT accounts); prepare → sign off (frozen snapshot, never changes) → marked filed by hand with the portal's reference; a prepared VAT settlement entry for the normal posting workflow; the deadline on the tax calendar; PDF and Excel. Needs the official form and its notes (§5). |
| V1-3 | **Running it on the owner's computer** | One command to install, one to start and stop, one to back up and restore (and a tested restore); upgrades that apply migrations safely after a backup; data kept in named volumes; sign-in with MFA on the local identity provider; a short guide. |
| V1-4 | **End-to-end check** | A scripted walk through a full year of a synthetic business as the owner would use it, across every module in sequence, checking that the numbers agree from screen to screen (ledger → statements → budget variance → KPIs → cash → projection → pack → VAT return). Everything found is fixed. A version 1 report closes it. |
| V1-5 | **Dependencies** | The 16 open dependency-update PRs merged or closed with a reason, one by one, each with all checks green. |

## 4. Acceptance
- **AC-V1** Each item above meets its "done" column, with tests, all CI gates green, and
  `docs/PROGRESS.md` updated.
- **AC-V2** The end-to-end walk-through (V1-4) passes from a clean install (V1-3).
- **AC-V3** Every VAT box shown says where its definition comes from and that it awaits
  professional verification.

## 5. What is needed from the owner
1. **The official VAT return form and its completion notes** (Cyprus Tax Department). The Tax
   Department's website refuses automated access, so the developer cannot read it; please
   download the form (VAT 4) and the notes in a browser and upload them. Until then V1-2 builds
   everything except the box definitions, which are data.
2. Later, a Cyprus tax professional to verify the VAT rules (#93) and corporate tax rules (#154).
