# 13 — Milestone 0 Implementation Brief: Foundations

Status: **AWAITING GO-AHEAD**. This is the pre-implementation brief required by the development directive. No code until approved.

## 1. Business purpose
M0 builds no user-visible features. It creates the guard rails every later feature relies on, so that
correctness and security are **enforced by tooling from the first commit** rather than by discipline alone:
- decimal-only money arithmetic;
- no sensitive data in logs;
- module boundaries (accounting vs tax vs planning);
- secret scanning;
- reproducible synthetic data, so nobody needs real data to develop.

## 2. Dependencies and regulatory requirements
- Depends on the approved ADRs 0001–0010 only. No external services or accounts are needed. Everything runs locally and in GitHub Actions.
- Regulatory relevance: GDPR data minimisation (log redaction), integrity of financial calculations (Decimal), and evidence that controls exist (CI gates as auditable controls).
- **Not included:** any cloud resources. M0-7 (Terraform) is written and validated (`terraform validate`/`plan` against no account) but **never applied** without separate approval.

## 3. Technical approach (one PR per item, in order)

| PR | Item | Contents |
|---|---|---|
| 1 | M0-1 Repo layout | `backend/` (Django 5.x project, `src/` layout, modules as Django apps with an `api.py` façade), `frontend/` (Vite + React + TS strict), `infra/`, `docs/`; `CONTRIBUTING.md`, `CODEOWNERS`, PR template (mirroring the directive's feature checklist), `.editorconfig`, licence header policy |
| 2 | M0-2 CI | GitHub Actions: **ruff** (lint + format), **mypy --strict** on domain packages, **pytest** + coverage gates, **import-linter** contracts (module boundaries; planning ↛ ledger internals), **Semgrep** with custom rules (`float(` / float literals in domain code, `except: pass`, logging of request bodies), **pip-audit** + `npm audit`/OSV, **gitleaks**; frontend eslint, tsc, vitest; Dependabot config |
| 3 | M0-3 Local dev | `docker compose`: PostgreSQL 17, Keycloak (dev realm with MFA required), MinIO (dev-only), Mailpit; `make dev` / `make test`; `.env.example` with no secrets |
| 4 | M0-4 Money library | `Money` value object (Decimal + ISO-4217), `RoundingPolicy`, allocation (largest-remainder, deterministic), `float` → `TypeError`; property-based tests (Hypothesis) |
| 5 | M0-5 Errors & logging | problem+json (RFC 9457) error base with stable codes; correlation-ID middleware; structlog JSON logging with an allow-list redaction processor; tests proving names, emails, TINs, IBANs and amounts don't reach logs |
| 6 | M0-6 Synthetic data | Seeded generator: "Demo Trading Ltd" (CY), a synthetic household, and a **profile generator** parameterised to resemble your business and personal finances (levels, seasonality, payment delays) with no real records. Output is deterministic per seed. |
| 7 | M0-7 IaC skeleton | Terraform modules for the staging layout (network, DB, storage, KMS), `validate` + `tflint` + `checkov` in CI; **not applied** |

Tooling choices: **uv** for Python dependency locking (hash-pinned), **pnpm** for the frontend, Python 3.13, Node 22 LTS.

## 4. Acceptance criteria and tests
- AC-M0-1 A clean clone runs `make dev` and `make test` successfully on Linux/macOS with only Docker + uv + pnpm installed.
- AC-M0-2 CI runs on every PR and blocks merge on failure of any gate in PR 2. Each gate is proven by a deliberately failing fixture test (e.g. a `float` in a domain module fails Semgrep; a cross-module import fails import-linter; a fake AWS key fails gitleaks).
- AC-M0-3 `Money("0.1") + Money("0.2") == Money("0.3")`; `Money(0.1)` raises `TypeError`; HALF_UP vs HALF_EVEN tests at .005 boundaries; allocation of €100 into 3 parts sums exactly to €100 (property tested over random amounts and ratios); currency mismatch raises.
- AC-M0-4 Unhandled exceptions return problem+json with `correlation_id` and no stack trace. The redaction test passes for the listed sensitive fields.
- AC-M0-5 The synthetic generator with the same seed produces byte-identical output. Generated data contains no real names or identifiers (it uses reserved/fictional ranges, e.g. invalid-checksum VAT numbers and test IBANs).
- AC-M0-6 `terraform validate`/`tflint`/`checkov` pass. No `apply` path exists in CI.
- AC-M0-7 Coverage for `money` is 100% branch.

## 5. Risks and licensing
| Item | Note |
|---|---|
| MinIO | AGPL-3.0, used **unmodified as a local dev tool only**, never distributed or served to customers. Acceptable. Production uses the managed S3-compatible service. |
| Semgrep | The engine is LGPL-2.1, and our custom rules are our own. Registry rules have their own licence, so only those permitted for internal CI use are included. |
| Keycloak | Apache-2.0. |
| Django, DRF, structlog, Hypothesis, ruff, mypy, import-linter, uv, React, Vite | BSD/MIT/Apache/MPL-2.0 (Hypothesis, test-only). Compatible. |
| Risk | Over-engineering M0 delays value. Mitigation: each PR is small (≤ 1–3 days), and M0 stays limited to these 7 items. |

## 6. Out of scope for M0
Authentication, tenancy, any database tables (beyond Django defaults), UI screens, and cloud deployment.
