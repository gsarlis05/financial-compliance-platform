# Runbook: ledger integrity check failed

**Severity:** high. The books of a workspace may be wrong or tampered with. Treat as a potential
security incident until the cause is known.

## How you find out
- `make ops-checks` (or the scheduled job) exits non-zero and prints `FAILED <tenant_id>: <checks>`.
- The structured log has an error event `ledger.integrity_check_failed` with `error_code`
  `ledger.integrity_failure`, the `tenant_id` and the failed check names in `job`. Alert on it.
- The workspace's **Integrity** tab shows a FAILED run with details (at most 50 per check).

## The checks
| Check | Fails when | Usual causes |
|---|---|---|
| `posted_entries_balance` | a posted entry's debits ≠ credits, or it has fewer than 2 lines | direct SQL bypassing the triggers; a migration bug |
| `balances_match_lines` | a stored account/period balance ≠ the sum of posted lines | a posting code bug; manual edits to `ledger_account_balance` |
| `numbers_are_gapless` | a journal's entry numbers or the posting sequence have gaps or duplicates | sequence rows edited; a restore of a partial backup |
| `no_untagged_postings_after_lock` | an entry was posted into a period after it was locked, without an unlock tag | guard trigger disabled or bypassed |
| `audit_chain_verifies` | an audit event's hash does not match its content or the previous hash | rows changed or deleted outside the application |

## First 30 minutes
1. **Do not "fix" data.** Do not edit, delete or re-run anything that writes to the ledger.
2. Record the run id, tenant id, check names and details. Open an incident ticket.
3. Ask the workspace owner to pause posting (or soft-close the open periods) until resolved.
4. Snapshot evidence: export the run (`GET /api/w/{slug}/integrity-checks`), take a database
   snapshot, and keep the logs for the time range since the last PASSED run.
5. Re-run the checks once (`POST /api/w/{slug}/integrity-checks` or `make ops-checks`) to rule out a
   transient read. A second failure confirms the incident.

## Investigation
- Compare against the last PASSED run to bound the time window.
- `DB_ROLE=owner python manage.py audit_verify` reports the first broken audit event per workspace;
  the events before it are trustworthy.
- For balance or numbering failures, list the affected entries' audit events (they record who
  prepared, approved and posted each one, with content hashes).
- Check the database logs for sessions that used a role other than `fcp_app` and for DDL
  (disabled triggers, altered policies).

## Resolution
- Corrections to posted data are made **only** through the application's workflows (reversal and
  adjustment entries, period unlocks with two approvers), never by SQL.
- A stored-balance mismatch caused by a code bug needs a reviewed, tested migration or a
  rebuild command approved in a PR. Never edit by hand. Production changes need product owner
  approval.
- If tampering is suspected: rotate database credentials, review access, and assess GDPR breach
  notification (72 hours, Art. 33) with the data protection contact.
- Close the incident only after a PASSED run. Write a short post-mortem.
