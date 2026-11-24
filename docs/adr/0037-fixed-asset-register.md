# ADR-0037: The fixed-asset register depreciates by schedule and only prepares draft entries
Status: **Proposed** (M6-1; awaiting product owner review in PR) · Date: 2026-11-12

## Context
Projections (M6-3) need depreciation from a fixed-asset register (doc 10 §4.1), and the books need
the same depreciation every month. The ledger's rules apply: sub-ledgers never write journal lines
directly (doc 05 §8), posted entries are immutable, and nothing posts behind a user's back.

## Decision
- **A separate `assets` module** (a sub-ledger, like banking) with a register per legal entity: the
  asset's cost, accumulated-depreciation and expense accounts (checked to belong to the entity and
  to be postable accounts of the right type), acquisition date and cost, residual value, useful life
  in months, method, and disposal.
- **Schedules are pure functions** (`assets/schedule.py`):
  - monthly, starting the month after acquisition and stopping before the month of disposal;
  - **straight-line** or **declining balance** (annual rate ÷ 12 on the book value, never below
    the residual value);
  - each month rounded to cents once; the last month takes the remainder, so the months add up
    to cost − residual value exactly, with no rounding plug (property-tested).
  The convention is shown with every schedule.
- **Preparing a month** creates **one draft journal entry** for the entity through the ledger's
  public interface: one debit to depreciation expense and one credit to accumulated depreciation
  per asset. It then follows the normal submission, approval and posting; the register never posts.
  - A month is prepared once (a unique database constraint).
  - If its draft is voided or rejected, the run is cancelled (kept) and the month can be prepared
    again.
- **Terms lock** once depreciation has been prepared for an asset (database trigger). Before that,
  they can be corrected. After that, only the disposal can be recorded, once. Assets and runs are
  never deleted; run lines are append-only.
- **Disposals** stop depreciation and show the gain or loss (proceeds − book value at the end of
  the month before). The user books the disposal entry, because settling the proceeds and the cost
  depends on facts only the user knows.
- New permissions `assets.read` (every role that can read the books) and `assets.manage`
  (preparers). Preparing also needs `ledger.entry.create`.

## Consequences
- The register and the ledger cannot drift silently: every month's depreciation in the books comes
  from a prepared draft that names its assets, and the schedule links to it.
- Mid-month conventions, revaluation, impairment, component accounting and tax depreciation
  schedules are not covered; they can be added as further methods or registers.
- Booking the disposal is manual. A prepared disposal entry can follow the same draft pattern.
