# 06 — Regulatory Rules Engine Specification

Status: **DRAFT for review** · ADR-0004

> **No rate or threshold shown here is authoritative.** Examples illustrate structure only.
> Real values enter the system through the curation workflow (§5) with a verified source.

## 1. Purpose and principles
- Deterministic, explainable computation of taxes and compliance values (VAT, corporate income tax, SDC, later others), separate from the ledger.
- **Rules are data, the engine is code.** Rule packs are declarative, versioned, effective-dated and signed. The engine is a small, heavily tested evaluator.
- **Same inputs + same rule version ⇒ same output, forever.** Historical computations are reproducible after rules change.
- Every result carries a **trace**: rule-version ID/hash, each step's inputs/outputs, rounding applied, and source references.
- The LLM is never in the calculation path (principle 8).

## 2. Concepts

| Concept | Description |
|---|---|
| **Rule pack** | A domain within a jurisdiction, e.g. `CY.VAT`, `CY.CIT`, `CY.SDC`, later `GR.VAT`. |
| **Rule version** | An immutable, semver'd definition with `effective_from`/`effective_to` and a `period_basis` (how applicability is decided: transaction/supply date, tax year, accounting period end). |
| **Parameter tables** | Effective-dated values inside a version (rates, thresholds, category lists) where finer-grained dating is needed, e.g. a temporary zero rate valid until a date. |
| **Computation graph** | Named steps (`taxable_profit = accounting_profit + add_backs − deductions`), each a pure function from a whitelisted operator set. |
| **Source references** | Links from each rule/parameter to a verified `SOURCE_DOCUMENT` locator (law, article, paragraph). |
| **Test cases** | Inputs → expected outputs, tagged `OFFICIAL_EXAMPLE`, `CURATOR` or `REGRESSION`. A version cannot be published unless all pass. |
| **Judgment hooks** | Points where the engine **cannot** decide (e.g. whether a supply is exempt, or whether a transitional provision applies). The engine requires a `JUDGMENT_RECORD` input approved by a qualified user, and otherwise returns `REQUIRES_JUDGMENT`, never a guess. |

## 3. Definition format (illustrative)

Stored as JSON (validated by JSON Schema), authored as YAML in a separate `rule-packs` repository,
and reviewed via PR before being imported.

```yaml
pack: CY.CIT
version: 2026.1.0
effective_from: 2026-01-01        # applies to tax years starting on/after
effective_to: null
period_basis: TAX_YEAR
rounding:
  default: { scale: 2, mode: HALF_UP }
parameters:
  cit_rate:
    - { value: "0.15", valid_from: 2026-01-01, source: SRC-CY-ITL-2025-AMEND#art-x }   # VERIFY
  loss_carry_forward_years:
    - { value: 7, valid_from: 2026-01-01, source: SRC-...#art-y }                     # VERIFY; transitional rules need judgment
steps:
  - id: taxable_profit
    expr: "accounting_profit + sum(add_backs) - sum(deductions)"
  - id: losses_utilised
    expr: "min(max(taxable_profit, 0), available_losses(loss_carry_forward_years))"
    judgment_hook: LOSS_TRANSITIONAL_ELIGIBILITY
  - id: chargeable_income
    expr: "max(taxable_profit - losses_utilised, 0)"
  - id: tax_due
    expr: "round(chargeable_income * cit_rate)"
outputs: [taxable_profit, losses_utilised, chargeable_income, tax_due]
```

The prior version `CY.CIT 2025.x` (12.5%) stays published with `effective_to: 2025-12-31`. That
is the canonical boundary test (§7).

**Expression language:** a small, sandboxed DSL (arithmetic on Decimal, `min/max/round/sum`,
conditionals, lookups into parameters, and whitelisted helper functions implemented in Python and
unit-tested). It is parsed to an AST and evaluated by our evaluator. **No `eval`, no arbitrary code,
no loops, no I/O.** Recommendation: a hand-written evaluator (small, auditable) over third-party
rule engines. An option to evaluate is DMN (FEEL) if curators need a standard notation; decide in
Milestone 2.

## 4. Applicability resolution
`resolve(pack, as_of, context) → RuleVersion`:
1. Choose the date per `period_basis` (e.g. supply date for VAT, tax-year start for CIT).
2. Select the **single** PUBLISHED version whose `[effective_from, effective_to]` contains it (DB exclusion constraint guarantees no overlap).
3. Within it, resolve each parameter by its own `valid_from/valid_to` against the relevant date.
4. No match → `NoApplicableRuleError` (visible, actionable). Never fall back to "latest".

Computations store `rule_version_id` + `definition_hash`. Re-running a FINAL computation uses the
stored version. If a newer *correcting* version exists for the same period (e.g. curator found an
error), the system flags affected computations ("rule revised since computation") for professional
review. It does not silently recompute.

## 5. Curation workflow (who may change rules)
```
Source intake ─► Source verification ─► Authoring ─► Tests ─► Peer review ─► Publish ─► Monitor
 (official text,    (curator #1 checks     (YAML PR)   (CI runs     (qualified     (signed,      (change
  hash, retrieval   authenticity,                     all cases)    curator #2,    immutable)    watch)
  date)             version, language)                              ≠ author)
```
- Curators are platform-level users with a professional qualification flag. **Author ≠ reviewer ≠ (optionally) publisher.**
- Publishing requires step-up auth and produces a signed `definition_hash` + audit event.
- Published versions are immutable. Fixes create a new version, and affected computations are flagged as above.
- **Change watch:** a recurring task (human-owned, optionally tool-assisted) monitors the Official Gazette, Tax Department circulars, and EU acts. Each item is triaged into a backlog ticket.

## 6. VAT specifics (MVP)
- **Tax codes** are defined by the VAT rule version: treatment (standard, reduced tiers, zero, exempt, reverse charge, intra-EU acquisition, out of scope), rate parameter reference, and mapping to VAT return boxes.
- **Line-level vs document-level rounding** is declared per rule version (structured invoices are typically computed per line and summed, but this must be verified).
- **VAT return preparation:** aggregate posted lines by tax code for the return period, map them to boxes, and run reconciliation checks (VAT control account balance vs return net). Output: `TAX_COMPUTATION` → `TAX_RETURN` (status PREPARED) → reviewer sign-off → export (PDF + structured data for manual entry/upload). **No automatic submission.**
- **Temporary rates** (e.g. a zero rate on specified goods valid until a set date) are parameter rows with `valid_to`. Category membership (which goods qualify) is a curated list + judgment hook for borderline items.
- Exemptions and reverse charge: classification requires a user-selected tax code. AI may *suggest* one, but the suggestion is a draft that the user accepts.

## 7. Test strategy (taxation)

| Category | Required cases |
|---|---|
| **Tax-year boundaries** | FY2025 computes at the 2025 version rate and FY2026 at the 2026 version rate. Non-calendar fiscal years straddling 1 Jan 2026: behaviour follows the law's applicability rule (**curator must specify**; until then the engine returns `REQUIRES_JUDGMENT`). Supply on 31 Dec vs 1 Jan for VAT uses the correct version. |
| **Effective dates** | Parameter valid until D: transaction on D uses it, D+1 doesn't. Gap between versions → `NoApplicableRuleError`. Overlap is impossible (DB constraint test). Retired version still reproduces historical results. |
| **Exemptions & special regimes** | Exempt supply excluded from output VAT but included in the appropriate box. Reverse charge produces equal output and input VAT. Partial exemption (input VAT recovery %) once in scope. |
| **Exceptional cases** | Negative taxable profit → zero tax, loss recorded. Loss utilisation limited by carry-forward years. Zero-value invoice. Credit notes in a later period. Rounding at 0.005. Huge values. Missing judgment → `REQUIRES_JUDGMENT`. |
| **Official worked examples** | Every example in Tax Department guidance/circulars relevant to the pack is encoded as an `OFFICIAL_EXAMPLE` test with its source reference. A pack can't be published with a failing or skipped official example. |
| **Determinism** | Same inputs + version → byte-identical result + trace hash. |
| **Engine safety** | DSL rejects unknown functions, attribute access, recursion, and over-long expressions. Fuzzed expressions never crash the worker (they return a typed error). |

## 8. Human review gates
- A computation moves to `APPROVED` only by a user with `tax.computation.approve`, and `FINAL` (with return sign-off) only by a user with `tax.return.signoff` + step-up. Sign-off hashes the computation result + trace.
- Material conclusions (configurable materiality) and every judgment hook require a `JUDGMENT_RECORD` with rationale and source references.
- UI shows: rule version, sources, judgments relied on, and an "**interpretation uncertain — professional review required**" banner whenever any judgment was flagged uncertain or any parameter is marked `provisional`.

## 9. Known limitations / risks
- Correctness depends on curator capacity and qualification. **This is a staffing requirement, not just a software one.**
- Complex reliefs (IP box, NID, group relief) are deferred and can be added as new steps/packs.
- Legal text interpretation is never automated. The engine encodes *decided* interpretations.
