# Runbook: correcting a locked period (period unlock)

Use this when an entry must be posted to, or reversed in, a period that is already **locked**
(for example, a missed supplier invoice found after the month-end close). Prefer posting the
correction in the current open period. Unlock only when the correction must be dated in the
locked period, for example because statutory figures depend on it.

## Rules the system enforces
- Only locked periods can be unlocked, and one request at a time per period.
- The request needs a reason (kept in the audit trail) and a window of 5 minutes to 8 hours.
- Two **different** approvers with `ledger.period.unlock_approve` (owner, finance manager, partner),
  neither of whom is the requester. Each approval needs a sign-in from the last 5 minutes (step-up).
- The window starts at the second approval. Entries posted during it are tagged with the unlock
  and remain visible as such in the trial balance (`restated_after_lock`).
- The unlock ends when the window expires or someone closes it early. The period stays locked
  throughout; only tagged postings are allowed while the unlock is active.

## Steps
1. **Prepare the correction first.** The accountant drafts the entry (or reversal) dated in the
   locked period and submits it. A reviewer approves it. Submitting and approving work while the
   period is locked; only posting is blocked.
2. **Request.** On **Periods**, the accountant enters the reason on the locked period and requests an
   unlock (API: `POST …/periods/{id}/unlock-requests` with `reason`, `window_minutes`).
3. **First approval.** An approver opens **Periods → Unlock requests** and approves. If asked, they
   sign in again.
4. **Second approval.** A different approver approves. The unlock is now ACTIVE until `active_until`.
5. **Post** the prepared entry within the window.
6. **Close** the unlock (`…/unlock-requests/{id}/close`) as soon as the entry is posted. Do not
   wait for the window to expire.
7. **Verify.** Run the integrity checks (Integrity tab). They must pass. Re-export the trial
   balance for the period if it was already shared.

## If something goes wrong
| Symptom | Meaning / action |
|---|---|
| 409 "This period already has an open unlock request" | approve, reject or close the existing one first |
| 403 segregation of duties | the requester or the first approver tried to approve again; ask someone else |
| 401 step-up required | the approver signed in more than 5 minutes ago; sign in again and retry |
| 409 period locked when posting | the window expired or was closed; request a new unlock |
| Posting was outside the window | impossible by design: the database guard refuses it. If the integrity check reports `no_untagged_postings_after_lock`, follow the [integrity runbook](integrity-check-failure.md) |

## Evidence for auditors
Every decision writes an audit event: `ledger.period.unlock_requested`, `ledger.period.unlock_approved`
(once per approver; the second records the active window), `ledger.period.unlock_rejected` and
`ledger.period.unlock_closed`. An expired window is recorded on the unlock itself (`closed_at` =
`active_until`), and every posting made during the window carries the unlock id. Export them via
`GET /api/w/{slug}/audit-events` (owners and finance managers).
