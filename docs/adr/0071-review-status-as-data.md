# ADR-0071: The review status of the rules and the engine is data
Status: **Accepted** (T-1, #254; brief 27) · Date: 2026-11-27

## Context
Until now, the platform marked its rules and its projection engine as unchecked in fixed code:
- the VAT codes, the VAT box rules and the corporate tax rules said "pending verification";
- the projection engine said `PENDING_PROFESSIONAL_REVIEW`.

On 2026-11-27 the owner checked them "for now" and asked to keep the option to correct them later.
The owner is not a tax professional, so the check must never read as a professional verification.

## Decision
- **One record, as data:** `fcp/core/reviews/reviews.json`.
  - It is append-only: a new entry changes a status, and the latest entry per subject applies.
  - The subjects are `CY:VAT_CODES`, `CY:VAT_BOX_RULES`, `CY:CORPORATE_INCOME_TAX` and
    `PROJECTION_ENGINE`.
  - The statuses are `PENDING`, `OWNER_CHECKED` and `PROFESSIONALLY_VERIFIED`.
  - A check needs a date and who made it, or the file is refused.
  - The wording in English and Greek is part of the same data.
- **Professional verification keeps its own flags.** The per-row `verified` fields of VAT codes
  and tax rule sets still mean "verified by a qualified tax professional". They stay `False`.
- **What reads the record:**
  - the VAT code list and the tax rules list (`review_status`, `review_note`);
  - a new `GET …/reviews` route;
  - the VAT report snapshot;
  - the VAT exports;
  - the projection, scenario and sensitivity outputs (`engine_status`, which is now
    `OWNER_CHECKED`), their Excel notes, and the report pack's forecast notice;
  - the dashboard scenario widget;
  - the validation summary;
  - the professional review list;
  - the screens' notes, through one `EngineReviewNote` component.
- **Pinned, never rewritten.** A VAT report pins both reviews in its snapshot, as they stood when
  it was prepared.
  - A report prepared earlier keeps saying "pending".
  - A report pack made earlier keeps the pending notice.
  - The engine's calculation output (its sources and hashes) does not include the status, so
    every earlier run still reproduces exactly.

## Consequences
- The status can change again, for example to `PROFESSIONALLY_VERIFIED`, or back to `PENDING` if
  the engine changes, by adding one entry to the record. Every screen follows.
- Corrections to the rules themselves are T-2 (#255): versions per entity, entered on a screen.
