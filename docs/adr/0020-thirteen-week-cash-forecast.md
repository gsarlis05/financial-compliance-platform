# ADR-0020: The 13-week cash forecast: inputs, dating rules and outputs
Status: **Proposed** (M3-7; awaiting product owner review in PR) · Date: 2026-11-04
## Context
The forecast answers "will we have enough cash over the next 13 weeks?" (doc 10 §3, AC-CW1–CW8).
It combines balances from the ledger with open items, scheduled commitments and estimates. It must
be reproducible (ADR-0017): a run must give the same numbers later, even after open items are
allocated, settings change or new postings arrive.
## Decision
- **Engine:** the `cashflow` module is a planning module (it never imports the ledger), and its
  engine is `CASH_13W` in the calculation framework.
- **Inputs are snapshotted.**
  - When a run is prepared, every input except the ledger balances is copied into the run's
    inputs (and so into its input hash):
    - open receivables and payables, with their expected dates;
    - obligation, loan and tax flows, with their version IDs;
    - manual items, settings and facility limits;
    - each customer's days late;
    - the warnings.
  - The opening cash is read from the ledger pinned at the run's watermark.
  - Re-running therefore reproduces the output hash exactly.
- **Opening cash** is the balance of the accounts mapped to `BS.CASH`, with everything posted up to
  the as-of date. Bucket 1 starts on the as-of date; every week runs Monday to Sunday (ISO).
- **Dating and nature** (doc 10 §3.2):
  - **Receivables:** COMMITTED, dated at the due date plus the customer's days late (M3-6).
  - **Payables:** COMMITTED, dated at the due date, or on the last chosen weekday on or before it
    (payables policy).
  - **Obligations, loans and tax:** the nature comes from their registers.
  - **Manual items:** always EXPECTED, and they need a reason.
  - **Disputed open items** are left out, with a warning showing their count and amount.
  - **Obligation and loan payments dated before the as-of date** are taken as paid (the bank
    shows them).
  - **Overdue** receivables, payables and unpaid tax fall in bucket 1, flagged.
  - **Past manual items** are left out, with a warning.
  - **Beyond the horizon:** flows after week 13 are reported as a total.
- **Outputs per week:**
  - the opening (ACTUAL in week 1, otherwise FORECAST);
  - flows by direction, category and nature, with lineage to each open item, schedule or manual
    item;
  - inflows, outflows, net and closing;
  - the minimum cash (TARGET) and headroom = closing − minimum;
  - undrawn facilities = limits − overdraft in use;
  - liquidity = closing + facility limits;
  - a shortfall flag when the closing is below the minimum.
  - The **first shortfall date** is the first day the running balance falls below the minimum.
- **Invariants** (a run that fails one is INVALID):
  - closing = opening + net;
  - opening(t+1) = closing(t);
  - every flow due within the horizon is counted exactly once.
- **Warnings:**
  - a bank account not reconciled within N days (7 by default) of the as-of date;
  - no cash accounts mapped;
  - disputed items left out;
  - past manual items.
- **What-ifs (M3-9).** A what-if applies overrides to a run's stored inputs and is computed on
  request. It is **never saved**, so it can never replace the base. The overrides are:
  - a timing shift for a customer or supplier and/or a category;
  - a percentage change, rounded to cents per flow;
  - a one-off with a reason.

  Every flow an override touches becomes HYPOTHETICAL. The base is computed again from the same
  pinned data and must reproduce the run's output hash. The result is both, week by week, with
  the difference. Saved scenarios come with the scenarios module (M5).
## Consequences
- **Testing:** the engine is tested against an independent reference calculation, including
  property tests over random flows and on the Demo Trading data. The golden 13-week fixture is
  marked `signed_off: false` until a finance professional has checked it (AC-CW5).
- **Size:** runs carry their inputs, from a few KB to a few hundred KB. Old runs can later be
  compacted.
- **Not yet built:** the dashboard (M3-10). Staleness and scheduled re-runs are in ADR-0021
  (M3-8).
## Alternatives considered
- **Re-reading registers at re-run time:** not reproducible, because allocations and versions
  change.
- **Pro-rating weekly amounts:** refused; flows are dated (AC-CW3).
- **Including disputed items:** this hides a known risk. Leaving them out with a warning makes the
  risk visible.
