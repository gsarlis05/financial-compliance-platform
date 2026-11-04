# ADR-0015: Bank statement imports run in a worker; reconciliation is a balance proof
Status: **Proposed** (M2-5; awaiting product owner review in PR) · Date: 2026-11-04
## Context
Bank files come from outside, and XML parsing is a classic attack surface (XXE, entity expansion).
The M2 brief asks for imports to run "in a worker task, not the request". The platform has no task
queue yet, and M2-4 (documents in S3) is not built yet. Reconciliation must prove that the ledger
agrees with the bank (AC-M2-5).
## Decision
- **Parsing:**
  - CAMT.053 goes through `defusedxml`, with DTDs, entities and external references refused.
  - CSV is read with a saved per-bank column mapping. The default mapping fits the synthetic
    export, and its optional columns may be absent.
  - Limits are 5 MB and 20,000 lines. Amounts must have at most two decimals.
  - Only `StatementFormatError` can escape the parsers. This is fuzz-tested on every CI run and was
    exercised with 50,000 extra cases while building.
- **Worker:**
  - The request validates the size, hashes the file and stores it as a `PENDING` import.
  - `python manage.py banking_process_imports [--loop]` processes pending imports per workspace
    under row-level security, using `SELECT … FOR UPDATE SKIP LOCKED`, so several workers are safe.
  - On AWS it runs as a small ECS service with the **runtime role**. That role may not list
    workspaces, so the worker finds work through `banking_pending_tenant_ids()`. This narrow
    `SECURITY DEFINER` function, owned by the maintenance role, returns only the IDs of workspaces
    with pending imports (the container smoke test proves this).
  - Reconciliations are append-only twice over: a trigger, and no UPDATE or DELETE privilege for
    the runtime role.
  - Development and tests process inline (`BANKING_PROCESS_INLINE`). Production settings force it
    off.
  - This database-backed queue is enough until a general task queue is chosen (Phase 2), and it
    needs no new infrastructure.
- **Raw files** are kept in the database, under row-level security, as evidence until object storage
  arrives (M2-4). Then they move to S3 with a per-tenant KMS context.
- **No duplicates:**
  - The same file is refused (unique SHA-256 per bank account, 409).
  - Overlapping statements add only new transactions. A line hash (date, amount, bank reference or
    text, and its occurrence within the file) is unique per bank account.
- **Matching:**
  - A statement line matches one *posted* line on the bank's ledger account with the same signed
    amount, and a ledger line matches at most one statement line. The database enforces both.
  - Automatic matching links a line only when the reference agrees, or exactly one candidate
    exists within 7 days. It never guesses between equal amounts.
  - Unmatched lines can be matched by hand, ignored (with a reason) or booked. Booking creates a
    draft entry (source `IMPORT`) that follows the normal approval workflow; the system never posts
    by itself. Open invoices with the same amount are suggested.
- **Reconciliation** is recorded only when the ledger balance of the bank's ledger account at a date
  equals the statement balance at that date (a database check). Records are append-only, and the
  latest one is the "last reconciled" date. Unmatched lines are reported but do not block: the
  balances are the proof, and matching is the tool for explaining a difference.
## Consequences
+ No parser runs inside a web request in production. Hostile files fail closed with a reason.
+ Re-importing is always safe. The audit trail records uploads, processing, matches, ignores and
  reconciliations.
− One more process to run on AWS (a worker service). The database grows with raw files until M2-4.
− Grouped matching (one ledger line for many statement lines, as in the demo's monthly summaries) is
  not automatic yet. Those lines stay unmatched, while the balances still reconcile.
