# ADR-0060: Four steps for a VAT return, adjustments, inclusions and amendments
Status: **Accepted** (V1-2d, #215; owner decision "four steps as in the PDF", 2026-11-23, brief 25
§4) · Date: 2026-11-23

## Context
V1-2a signed a VAT report off in one step. The owner's specification asks for:
- four steps, Draft → Reviewed → Finalised → Filed, recording the preparer, reviewer and times;
- manual adjustments, each with an amount, a box, a reason, evidence and an approval;
- an immutable snapshot at finalisation;
- no line reported twice;
- a visible list of differences when entries arrive later;
- amendments that follow the Cyprus procedure, never pushed into the current return
  automatically.

## Decision
- **Statuses** `DRAFT`, `REVIEWED`, `FINALISED`, `FILED`, `SUPERSEDED`.
  - **Review** (`tax.vat.sign_off`) freezes the figures. It is refused:
    - before the period ends;
    - when the books changed since the report was prepared;
    - while an adjustment is still proposed.
  - A reviewed report can be **sent back to draft** with a note, which clears the review.
  - **Finalise** (`tax.vat.sign_off`) follows the review. It is refused if the books changed
    since. It records the inclusions.
  - **Filed** needs the date, the portal's reference and a note of the evidence, for example
    where the acknowledgement is kept.
  - The reviewer and the finaliser are never the preparer, except in a one-person workspace,
    where the report is marked self-approved (V1-1).
  - The database enforces every transition, as for every approvable object.
- **Reports signed off under V1-2a become finalised.** Their single sign-off was the review and
  the finalisation, by someone other than the preparer, so both are recorded as that person at
  that time. The column `signed_off_*` is renamed `finalised_*`.
- **Adjustments** (`tax_vat_adjustment`):
  - Each changes one box (not 3 or 5, which follow) by a signed amount in cents, with a reason
    and evidence.
  - It starts as proposed, on a draft only. It is approved by `tax.vat.sign_off`, never by its
    author except in a one-person workspace, or rejected or withdrawn. It is decided once and
    never changed or deleted (trigger).
  - The return is shown as from the books, adjustment and final for each box, with 3, 5, the
    rounding and the checks following the final amounts. The ledger and the snapshot never
    change. Because adjustments are closed from the review on, the final figures of a finalised
    report are as fixed as its snapshot.
  - A new version carries the approved adjustments over as proposals, to be decided again.
  - The evidence is a note, not a file. Documents can be linked only to journal entries today, so
    a document link is left for later.
- **Inclusions** (`tax_vat_inclusion`):
  - Finalising records every line of the return. A unique index on active inclusions allows a
    line in only one active return.
  - The inclusions of an earlier version become inactive when it is superseded.
  - Inclusions are never deleted.
- **Differences:** a reviewed, finalised or filed report lists the lines posted or reversed in
  its period since it was prepared, with the change to each box. They are only shown, never moved
  into this return or another one; a correction is a new version.
- **Amendments:**
  - A new version of a finalised or filed report shows the version it corrects, that version's
    filing reference, and the change to each box.
  - The screen tells the owner to file the correction following the Tax Department's procedure
    with an adviser. The procedure itself is not described, because the official guidance could
    not be read.

## Consequences
- The report matches the specification's workflow. Every step, adjustment and decision is
  audited and enforced by the database.
- The settlement entry still moves the ledger's VAT balances. An adjustment that is not in the
  books is not in the settlement, and the owner posts it if needed.
- Still to come: schedules and the reconciliation (V1-2e), imports (V1-2f) and VIES (V1-2g).
