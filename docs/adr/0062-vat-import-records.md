# ADR-0062: Import records behind import VAT claims
Status: **Accepted** (V1-2f, #217; brief 25 §3) · Date: 2026-11-23

## Context
Import VAT paid at customs is deductible in Box 4, but only against the customs declaration.
The owner's specification asks for:
- each import's customs reference and date;
- its taxable value;
- the import VAT, with evidence;
- its recovery;
- a link to the ledger;
- no claim made twice.

## Decision
- **One record per customs declaration** (`tax_vat_import`). Each record holds:
  - the entity and the posted entry that claims the import VAT (an import code on the input VAT
    account);
  - the declaration's reference and date;
  - the taxable value and the import VAT it shows;
  - the evidence: a document attached to that entry, held by its id and filename.
- **The documents module offers `entry_document`.** It returns a document only if it is attached
  to the given entry, so evidence is always the entry's own document. A composite tenant key ties
  the record to the documents table.
- **No double claims.** The database allows one active record per customs reference and one per
  entry. Voiding and re-recording is the only correction. A record is voided once, with a
  reason, and never while its entry is in a finalised return; the database refuses that too.
  Records are never edited or deleted.
- **In the report**, the records of the period's import entries are frozen in the snapshot and
  are part of the figures' fingerprint. Recording or voiding one therefore asks for a regenerated
  draft. The report checks:
  - every import VAT claim has its record (`IMPORT_WITHOUT_RECORD`);
  - the record's import VAT equals the VAT claimed, recoverable and not (`IMPORT_VAT_MISMATCH`);
  - the taxable value at the code's catalogue rate gives that VAT (`IMPORT_VALUE_MISMATCH`).
- **The imports schedule** shows, for each import, the reference, date, taxable value, the VAT
  claimed (recoverable and not, from the line's recovery details) and the evidence. Every
  export carries it.
- **The value of imports** still goes into no box. The specification does not map it, so it
  stays an unsupported line (ADR-0059).

## Consequences
- Every import VAT figure in Box 4 traces to a customs declaration and its document. The same
  declaration cannot support two claims.
- Customs references are not checked against the Customs Department; their format is not
  validated.
