# Projection engine: professional validation package

Status: **NOT CERTIFIED. Pending review by a qualified independent professional.**
Engine status in the code: `VALIDATION_STATUS = "PENDING_PROFESSIONAL_REVIEW"`
(`backend/src/fcp/modules/projections/engine.py`); it is shown on every projection screen and
export, and it changes only when a signed review is recorded (owner decision D9, 2026-11-15).

This package lets an independent accounting or finance professional (ACA, ACCA, CPA or
equivalent, with financial-modelling experience) check the 24-month three-statement projection
engine. It was prepared by the development team (with an AI assistant) and has **not** been
examined or signed by a qualified reviewer.

| # | Document | What it holds |
|---|---|---|
| 1 | [01-scope-and-method.md](01-scope-and-method.md) | What is validated, the conventions, rounding rules, the EUR 0.01 tolerance, how independence is achieved and its limits |
| 2 | [02-scenarios.md](02-scenarios.md) | The six 24-month scenarios (base golden model and the edge cases) with figures worked out by hand |
| 3 | [results/summary.md](results/summary.md) | Generated: the comparison of the engine with the independent model, every line of every month; reconciliation and invariant results; results by area |
| 4 | [03-discrepancy-report.md](03-discrepancy-report.md) | Every difference found, its cause and its treatment, including issues found and corrected while building the package, and observations for the reviewer |
| 5 | [04-acceptance-checklist.md](04-acceptance-checklist.md) | Passed and failed tests, unresolved issues, corrective actions, and the review still required |
| 6 | [05-reviewer-sign-off.md](05-reviewer-sign-off.md) | The form the reviewer completes and signs |
| - | `scenarios/*.json` | The inputs of each scenario (read by both models) |
| - | `model/independent_model.py` | The independent model (Python standard library only; imports nothing from the platform) |
| - | `results/<scenario>/` | Monthly statements from the independent model and from the engine, the line-by-line comparison and the model's reconciliation, as CSV |
| - | `results/validation-workbook.xlsx` | For review in Excel: each scenario's 24 months of statements, with reconciliation checks as live formulas |
| - | `results/tax-payments.md` | Every tax payment of every scenario |

## Reproduce
```bash
python3 docs/validation/model/independent_model.py docs/validation/scenarios/s1-base.json
cd backend && uv run python -m fcp.devtools.validation          # regenerate results/
cd backend && uv run python -m fcp.devtools.validation --check  # what CI runs
```
The check is also a test (`backend/tests/validation/test_package.py`), so every change to the
engine is compared with the independent model before it can be merged.
