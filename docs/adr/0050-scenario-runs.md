# ADR-0050: Scenario runs through the unchanged projection engine, with lineage by override
Status: **Proposed** (M7-2, #177; awaiting product owner review in PR) · Date: 2026-11-16

## Context
Doc 10 §8 and FR-S2 ask that a scenario's effects be shown on cash, the three statements,
liquidity and debt, that every changed value be traceable to the override that changed it, and
that scenarios never change budgets or forecasts; promoting one is an explicit action that enters
the normal approval. Doc 12 §1 asks for the property "a scenario with zero overrides = base". ADR-0049
defined scenarios as typed overrides on an approved assumption set.

## Decision
- **Same engine, same checks.** A scenario run loads the projection's pinned inputs for its base
  (`projections.pin` / `load_input`), applies its overrides in order to a copy of the engine input
  (`scenarios/apply.py`, a pure function), and runs the projection engine unchanged. The eight
  invariants apply, and a scenario that fails one is `INVALID` and says where.
- **Two engine inputs, scenarios only:** `extra_capex` (an investment with its own useful life in
  a month that already has capex of another life) and `settlements` (a one-off payment of part of a
  held liability: other payables, or VAT and other taxes payable). Both are empty for every
  projection, so projection results and the validation package are unchanged (their tests pass).
  When settlements exist, the cash flow statement has a `CF.SETTLEMENTS` line in operating cash
  flow and the held-lines invariant allows for them.
- **Lineage by override.** The run is computed step by step: the base, then with the first
  override, the first two, and so on. A value's change at step *k* is the effect of override *k*,
  listed in its lineage with the override's id and the amount. The "what changed and why" table
  (revenue, EBITDA, net income and net cash flow over the horizon; cash and debt at its end) sums
  these effects; by construction they add up exactly to the total difference. This costs one engine
  run per override (at most 50): 1.6 s for 50 overrides over 36 months in the development
  container, within the 3 s target of doc 01.
- **Natures.** Every projected value of a scenario is `HYPOTHETICAL`; the opening balance sheet
  stays `ACTUAL`. With no overrides, the scenario's values are the base's values exactly (property
  test), relabelled `HYPOTHETICAL`.
- **In memory, or saved.** The comparison is computed on request on the current books and not
  stored. Saving records a calculation run of kind `SCENARIO` (engine `SCENARIO` version 1) with the
  base's projection inputs and the overrides as they were pinned, so it reproduces like any run.
  Engines can now declare `publishable = False`; scenario runs are never published.
- **Promotion** creates a new assumption-set **draft** (its own family) from the base with the
  overrides written into its values (source `MANUAL`) and new loans; it then needs the normal
  approval with `planning.publish`. Overrides a set cannot hold (a liability settlement; capex with
  another life in a month that already has capex) make promotion refuse, listing them.
- **Permissions.** Computing a comparison, saving a run and promoting need `planning.run`; listing
  saved runs needs `planning.read`.

## Consequences
- Scenario results inherit the projection engine's status, `PENDING_PROFESSIONAL_REVIEW` (#153);
  the comparison says so.
- KPIs and DSCR on scenario figures come with M7-6; the screens with M7-7.
- Trade payables cannot be settled by a one-off (they follow DPO every month); timing shifts of a
  line by whole months drop what moves past the window, and say how much.
