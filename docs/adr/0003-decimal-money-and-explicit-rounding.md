# ADR-0003: Decimal money type and explicit rounding
Status: Proposed · Date: 2026-11-03
## Context
Binary floating point cannot represent decimal currency exactly.
## Decision
`Money(Decimal, currency)` only; `float` input raises; DB `NUMERIC(19,4)` amounts and `NUMERIC(28,10)` rates; JSON strings at the API; every scale change takes an explicit `RoundingPolicy` that is recorded in traces; lint rule against `float(` in domain code; property-based tests.
## Consequences
+ Exact, reproducible results. − Slight verbosity; frontend needs a decimal library for previews (server stays authoritative).
