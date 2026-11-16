# 05 — Financial Ledger Specification

Status: **APPROVED (2026-11-03)** · Data model: [03 §2](03-entity-relationship-model.md)

## 1. Principles
1. **Double entry:** every posted entry has ≥ 2 lines and Σdebits = Σcredits in functional currency (and in transaction currency when all lines share one currency).
2. **Immutability:** a posted entry and its lines never change. History is corrected only by new entries.
3. **Exactness:** amounts are `Decimal`. Every rounding is explicit, deterministic and recorded.
4. **Traceability:** every entry links to its source (document, import row, computation, AI draft), preparer, approver and audit events.
5. **Period integrity:** postings respect period status. Closed history is protected.

## 2. Entry lifecycle

```
           create/edit                submit              approve               post
  (none) ───────────────► DRAFT ───────────────► SUBMITTED ─────────► APPROVED ─────────► POSTED
                            ▲   │ discard                │ reject            │ (auto-post if policy)    │
                            │   ▼                        ▼                   │                          │ reverse
                            │ VOID_DRAFT              REJECTED ── edit ──────┘(back to DRAFT)          ▼
                            └────────────────────────────────────────────────            new REVERSAL entry (own lifecycle)
```

- **DRAFT** and **SUBMITTED** entries are mutable only by the preparer (or users with edit permission). Edits are audited with diffs.
- **Approval policy** (per entity, configurable): `none` (preparer may post), `threshold` (approval required above amount X or for specific accounts/entry types), `always`. SoD: approver ≠ preparer when approval is required.
- The approval binds to `content_hash` (canonical hash of header + lines). Any change after approval invalidates it.
- **Posting** (single DB transaction, `SERIALIZABLE` or row-locked):
  1. Lock the period row `FOR SHARE` and check the status (OPEN, or SOFT_CLOSED with `ledger.period.post_soft_closed`).
  2. Validate: accounts postable/active/same entity, line rules, balance, FX rate present, tax codes valid for the `accounting_date` per rule version.
  3. Assign a gapless `entry_no` from the per-(journal, FY) sequence row (`SELECT … FOR UPDATE`).
  4. Set `POSTED`, `posted_at`, `posted_by`, and compute the final `content_hash`.
  5. Upsert `account_balance` rows (optimistic `version`).
  6. Write audit event(s) + outbox event `ledger.entry.posted`.
  7. The deferred constraint trigger re-verifies balance at commit.
- **Idempotency:** create/post APIs accept an `Idempotency-Key`. Imports derive keys from source row hashes, so duplicate imports are rejected with a visible report.

## 3. Line rules
- Exactly one of debit/credit > 0 per line, both in transaction and functional currency.
- `txn_currency` must equal the account currency if the account is currency-restricted.
- `debit_func = round(debit_txn × fx_rate, 2, HALF_UP)` (functional currency EUR, 2 dp). The FX rate is stored on the line with its `fx_rate_id` source. For EUR lines, rate = 1 exactly.
- **Rounding residual:** if converted lines do not balance in functional currency only because of per-line rounding, the system adds an explicit **rounding line** to a designated "FX rounding difference" account. This is allowed only when |residual| ≤ 0.01 × (number of foreign-currency lines), so larger differences are rejected as errors. The rounding line is flagged `system_generated`, never hidden.
- Memo/description are required on manual entries. Counterparty is required on control accounts (AR/AP).
- Control accounts (AR, AP, VAT control, bank) can be restricted to postings from their sub-ledger/module only.

## 4. Corrections

| Situation | Mechanism | Requirements |
|---|---|---|
| Error in a posted entry | **Reversal**: a new entry with mirrored lines (debits↔credits), `entry_type=REVERSAL`, `reverses_entry_id` set, then a new correct entry | Reason required. Reversal date = original date if that period is open, else the first open period (user chooses, and the default is recorded). An original can be reversed **once**; trying again raises `AlreadyReversedError`. |
| Partial correction / reclassification | **Adjusting entry** (`ADJUSTMENT`) referencing the original(s) | Reason + approval per policy |
| Closed-year audit adjustments | Post to the **adjustment period** (period 13) of that FY, if the FY is not hard-locked | `ledger.period.post_soft_closed` + approval |
| Locked period requires change | **Unlock workflow**: request with reason → 2 approvers (Partner + another) with step-up auth → time-boxed unlock → auto re-lock. All postings during the window are tagged with the unlock request ID | Visible on reports as "restated after lock" |

There is no "edit posted entry" path anywhere, including admin/support.

## 5. Periods & year-end
- Fiscal year: arbitrary start date (Cyprus companies commonly use the calendar year, but others are supported), 12 regular periods (or custom) + optional adjustment period.
- States: `OPEN → SOFT_CLOSED → LOCKED`. Moving forward needs `ledger.period.soft_close` / `.lock`. Moving backward needs the unlock workflow.
- Pre-close checklist (informational, blocking where configured): unposted drafts in period, unreconciled bank accounts, suspense account balance ≠ 0, VAT return status.
- Year-end close: a system `CLOSING` entry moves income/expense balances to retained earnings (generated, reviewed, posted). An `OPENING` entry for the next FY is generated from balance-sheet balances. **Reconciliation check:** opening TB(FY+1) = closing balance-sheet TB(FY).
- Re-opening a closed year reverses the closing entry via the standard mechanism.

## 6. Multi-currency
- Functional currency per entity (EUR for CY). Presentation-currency translation is out of scope for the MVP.
- FX rates: ECB reference rates imported daily (with source and hash), and manual rates allowed with a reason + document. Rate selection policy per entity: transaction date rate (default) or monthly average.
- Period-end revaluation of monetary items: a system-generated `FX_REVAL` entry (reviewed), reversed at the start of the next period if the entity policy says so. Realised vs unrealised FX accounts are distinct.

## 7. Balances, reports, reconciliation
- `account_balance(entity, account, period, currency)` stores debit/credit totals, maintained at post time.
- **Trial balance** = Σ balances up to a date or period. It must satisfy Σdebit = Σcredit (functional), or the report refuses to render and raises an integrity alert.
- Nightly **integrity job**: (a) every posted entry balances; (b) `account_balance` = Σ lines per key; (c) no posted lines in LOCKED periods newer than the lock timestamp unless they carry an unlock tag; (d) entry_no gapless; (e) audit hash chain verifies. Failures appear in an admin integrity dashboard and page on-call.
- **Financial statements:** accounts map to IFRS line keys (`report_mapping`, versioned). The balance sheet must satisfy Assets = Liabilities + Equity (incl. current-year result). P&L net result = change in retained earnings after closing. Any unmapped account with a non-zero balance blocks statement finalisation.

## 8. Sub-ledger integration (bank, sales/purchases, tax)
Modules never write `journal_line` directly. They call `ledger.api.create_entry(...)` with a
`source` and `source_ref`, so the same validation, approval and audit apply.

## 9. Test plan (ledger)

| Category | Cases |
|---|---|
| Balancing | Balanced 2-line, n-line, multi-currency entries post OK. Off by 0.01 → `UnbalancedEntryError`. Single line rejected. Zero-amount line rejected. Negative amounts rejected. Both sides on one line rejected. DB trigger rejects an unbalanced post even if the app check is bypassed (direct SQL test). |
| Property-based | Random balanced entries → TB always balances. reverse(reverse-able entry) nets every account to zero. Σbalances = Σlines. Posting order doesn't change TB. |
| Rounding | 3 × 33.333 USD at rate 1.0837 → rounding line ≤ limit and explicit. Residual over the limit rejected. HALF_UP vs banker's rounding at .005 boundaries. Large amounts (10^13) without overflow. No float anywhere (lint + `TypeError` on float input). |
| Immutability | UPDATE/DELETE on posted rows fails at the DB. API has no route. Second reversal fails. Approval invalidated when content changes after approval. |
| Period locking | Post into LOCKED → `PeriodLockedError`. SOFT_CLOSED without permission → denied, with permission → OK + audited. Date outside period ranges rejected. Unlock requires 2 distinct approvers + step-up and expires automatically. Concurrent post while locking resolves deterministically (lock wins or post commits first; never half-state). |
| Sequencing & concurrency | 50 parallel posts → gapless unique entry_no. Idempotent retry doesn't double-post. |
| Year-end | Closing entry zeroes P&L. Opening TB = prior closing BS. Re-open/close cycle reproduces the same balances. |
| FX | Missing rate blocks posting with an actionable error. Revaluation + auto-reversal nets to zero over two periods. |
| Statements reconciliation | BS balances. P&L result = retained-earnings movement. Golden-file statements for a sample company. An unmapped account blocks finalisation. |
| Security | SoD: preparer cannot approve own entry. Cross-tenant/entity account reference rejected (composite FK). Permissions per transition. |

## 10. Sample data (Milestone 1 fixtures)
"Demo Trading Ltd" (CY, calendar FY2025 + FY2026, EUR) with a ~60-account IFRS-aligned CoA, opening
balances, 200 synthetic entries (sales, purchases with VAT, payroll accrual, USD supplier invoice
and payment with FX gain), one reversal, one adjustment-period entry, and a locked Q1. Fully
synthetic; no real persons or companies.

## 11. Known limitations (MVP)
No consolidation/intercompany elimination, no presentation-currency translation, no fixed-asset
register (manual depreciation entries), no accruals automation.
