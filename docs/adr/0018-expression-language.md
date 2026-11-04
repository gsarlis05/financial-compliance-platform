# ADR-0018: A hand-written, unit-typed Decimal expression language
Status: **Proposed** (M3-3; awaiting product owner review in PR) · Date: 2026-11-04
## Context
KPI formulas, driver formulas and goal metrics (Phase 2), and later tax rule steps (M9), are written
as formulas (doc 10 §2.2, doc 06 §3). Formulas are user and curator input, so evaluating them must
be safe. They must also compute in Decimal, reject unit mistakes (EUR + days) before running, and
never turn a zero denominator into 0 or infinity. Doc 06 left open whether to adopt DMN (FEEL)
instead of writing our own.
## Decision
We write our own small language, `metrics.expr`, with three stages.
- **Parser:**
  - a hand-written lexer and recursive-descent parser;
  - no `eval`, no Python `ast`, no attribute access, no loops and no I/O;
  - a formula reaches only the variables and reference functions passed to
    `compile_expression`.
- **Checker:** each formula is type- and unit-checked before it is evaluated.
  - The units are EUR, ratio, percent, days, count and times. A bare number takes the unit of the
    other operand.
  - `+`, `-`, comparisons, `min`/`max` and the branches of `if` need the same unit.
  - Ratio and percent scale any unit, and EUR × count is EUR.
  - Dividing two values of the same unit gives a ratio, and EUR ÷ count is EUR.
  - Everything else is rejected with a code and a position.
- **Evaluator:**
  - Decimal arithmetic with 28 significant digits, HALF_UP for `round`, and short-circuit
    `and`/`or`.
  - Division by zero, and `divide_positive` with a denominator that is not positive, give
    `NotMeaningful(reason)`. That propagates through every operation and is stored as the run
    value's reason (`formula_value`).
- **Limits:** 2,000 characters, 400 tokens, nesting depth 24, 28 digits per number and 20 arguments
  per call. Errors are always `ExpressionError` or `EvaluationError`; fuzzing with more than 14,000
  cases per CI run checks this.
- **Lineage:** each reference call (for example `metric(key=REV.SALES, period=…)`) is recorded with
  its arguments for the run's lineage.
## Consequences
- The language is small enough to audit, and has no dependency or licensing question.
- The same evaluator serves the rules engine in M9, which adds its own reference functions
  (parameters, lookups).
- Curators learn a small, documented syntax instead of FEEL. A FEEL front end could be added later
  that parses to the same tree.
- New units or unit rules are code changes, reviewed in a PR.
## Alternatives considered
- **DMN/FEEL engines:** a large surface; no Decimal-first Python implementation with unit typing.
- **`asteval` and similar sandboxes:** they evaluate Python, use floats by default, and have had
  sandbox escapes.
- **Spreadsheet engines:** float semantics and opaque formulas.
