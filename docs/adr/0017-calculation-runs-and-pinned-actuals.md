# ADR-0017: Calculation runs: natures as types, pinned actuals, hashed and immutable runs
Status: **Proposed** (M3-2; awaiting product owner review in PR) · Date: 2026-11-04
## Context
ADR-0009 and doc 10 §1–§2.3 require four things of every planning number (forecasts, KPIs, budgets,
projections):
- it has a nature;
- it is never mixed silently with numbers of another nature;
- it is reproducible from pinned inputs;
- it is explainable.

The actuals read model (M2-7) only answers "as of now". A run re-computed after new postings would
therefore see different actuals, even though the run recorded its watermark.
## Decision
- **Natures as types** (`metrics.nature`):
  - `ActualSeries` and `PlanSeries` (one non-actual nature each) have no `+` or `-` between
    each other. mypy rejects the mix (the operator types do not match), and the runtime raises
    `NatureMixError`. A plan series combines only with the same nature; `relabel()` makes an
    explicit change of nature.
  - Only `blend(actual, plan, cutover)` combines the two. It returns a `BlendedSeries` that has
    no arithmetic, and each of its points keeps its own nature.
- **Pinned actuals** (`reporting`):
  - `actuals_monthly`, `cash_daily` and `opening_net` take a `watermark`. They return the current
    facts minus the lines of entries posted after that watermark.
  - This is exact, because posted entries are immutable and `posting_seq` only grows.
  - A fact that existed only because of later postings disappears. A watermark that has not been
    reached is refused.
- **Runs** (`metrics.calc`):
  - An engine has `load(ctx, inputs)`, which reads only data pinned by the inputs, and
    `compute(inputs, data)`, a pure function.
  - `execute` stores the inputs:
    - kind;
    - engine version;
    - entity;
    - as-of date;
    - the current watermark;
    - `refs`, canonicalised to plain JSON, with floats refused.
  - It also stores their SHA-256, every value with its nature, unit and lineage, and the SHA-256
    of the canonical output.
  - Invariants decide VALID or INVALID. An engine exception is kept as a FAILED run; a user error
    (permission, validation) stores nothing.
- **Values** are stored exactly as computed: `numeric(50,28)`, with no rounding by the database.
  The framework refuses values that would not fit.
- **Canonical hashing:**
  - dictionary keys are sorted;
  - Decimals lose trailing zeros only, and are never rounded;
  - dates are ISO dates;
  - floats and datetimes are refused.
- **Reproduce** loads and computes again from the stored inputs, and compares the output hashes. It
  also re-hashes the stored values, and reports an engine version change instead of comparing.
- **Immutability (database triggers):**
  - A run is inserted RUNNING or FAILED, and a deferred check makes sure it is finished in the same
    transaction.
  - A finished run can only become stale, and a valid one published, each once and never back.
  - Results and lineage are inserted only while their run is RUNNING, and are append-only for the
    runtime role. Nothing is deleted.
- **Permissions:**
  - `planning.read`: all read roles;
  - `planning.run`: preparers;
  - `planning.publish`: sign-off roles.
## Consequences
- Every planning feature in M3–M5 uses one framework, and AC-CF1, AC-CF3 and AC-CF4 are tested on
  it.
- Pinned reads cost one extra query over the postings made after the watermark, which is small for
  recent runs and grows with age. Old runs that are re-run often can later be served from a stored
  snapshot.
- Engines must pin everything else they read (assumption-set and plan versions, open items as of
  the watermark). M3-4 to M3-7 do this for their inputs.
- Nature mixing between two plan natures still needs a deliberate `relabel()`.
## Alternatives considered
- **Snapshotting all inputs into each run:** exact, but it duplicates the ledger per run.
- **Read-model history per watermark:** heavy writes.
- **Natures as a field only:** mixing would be caught at runtime only, not by type checking.
