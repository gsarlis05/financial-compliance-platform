# ADR-0004: Regulatory rules as versioned declarative data evaluated by deterministic code
Status: **Accepted** · Date: 2026-11-03 (accepted by product owner 2026-11-03)
## Context
Tax law changes (e.g. the Cyprus 2026 reform) must apply by effective date while historical periods stay reproducible. Rules require professional verification.
## Decision
Rule packs (YAML → validated JSON) with effective-dated versions and parameters, source references, mandatory test cases (incl. official examples), a two-person publish workflow, and immutable published versions. They are evaluated by a small sandboxed DSL interpreter producing a full trace. Unresolvable interpretations return `REQUIRES_JUDGMENT`.
## Consequences
+ Rules ship independently of code, are auditable and reproducible. − Requires qualified curators; the DSL must stay deliberately small.
## Alternatives considered
Hard-coded rules (code release per law change, poor auditability); generic rule engines/Drools (heavy, harder to audit); DMN/FEEL (re-evaluate in Milestone 3).
