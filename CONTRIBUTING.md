# Contributing

## Ground rules
- Planning documents and ADRs (`docs/`) are the source of truth for scope and architecture. A change that contradicts an accepted ADR needs a new ADR first.
- **One pull request per backlog item** (`docs/planning/08-implementation-backlog.md`), small and reviewable. Every PR is reviewed by the product owner before merge (`.github/CODEOWNERS`).
- Fill in the PR template's feature checklist.
- **Never commit real customer, client or personal data.** Use the synthetic data generator. `dev` and `staging` hold synthetic data only (ADR-0010).
- **Never commit secrets.** Configuration comes from environment variables; `.env` files are git-ignored, and `.env.example` documents the variables with placeholder values only.
- No deployment and no migration is applied to any shared or deployed environment without explicit approval.

## Engineering rules (enforced in CI where possible)
- Money is `Decimal` via `fcp.core.money`. Never use binary floating point for financial values (ADR-0003). On the frontend, money travels as decimal strings.
- Modules communicate only through `fcp.modules.<name>.api`. Planning modules never import ledger internals (ADR-0001, ADR-0007).
- Errors are visible and actionable: no silent `except: pass`.
- Logs carry identifiers only, never personal data, document content or amounts.

## Layout
```
backend/    Django project (src/fcp), tests, uv-managed dependencies
frontend/   Vite + React + TypeScript (strict), pnpm-managed dependencies
infra/      Infrastructure as code (never applied without approval)
docs/       Planning documents and ADRs
```

## Local commands
```
make dev         # first run: creates .env with random secrets, installs deps,
                 # starts PostgreSQL 17, Keycloak, S3 (SeaweedFS), Mailpit, runs migrations
make run-backend # http://localhost:8000      make run-frontend  # http://localhost:5173
make dev-down    # stop services (keeps data)  make dev-reset    # delete local data
make test        # backend + frontend tests
make lint        # linters, type checks, module boundaries, no-float rule
make security    # Semgrep project rules + gitleaks (needs Docker)
make prove-gates # proves each custom gate rejects a deliberate violation
```

## CI gates (all block merge)
| Gate | Tool |
|---|---|
| Lint and format | ruff, ESLint (strict type-checked) |
| Types | mypy `--strict` (backend), `tsc` strict (frontend) |
| Tests and coverage | pytest (branch coverage at least 90%), Vitest |
| Module boundaries | import-linter: public `api.py` only, `fcp.core` independent, planning and AI never import the ledger |
| No floating point in domain code | `tools/fcp_lint/no_float.py` (AST) and Semgrep `fcp-float-call` |
| Project security rules | Semgrep (`.semgrep/`): swallowed exceptions, logging request payloads, SQL string building |
| Secrets | gitleaks over the full history |
| Dependencies | pip-audit, `pnpm audit` (high and critical block), Dependabot weekly |
| Gate proof | `scripts/ci/prove-gates.sh` injects violations in a temp dir and expects failures |
Prerequisites: Python 3.13 with uv, Node 22 with pnpm 10, and Docker with Compose.

Local services (all bound to 127.0.0.1): PostgreSQL 17 on 5432; Keycloak on 8080 (realm `fcp-dev`,
admin console credentials in `.env`; **MFA is required**: every user must configure TOTP at first
login, and WebAuthn is available); S3-compatible storage on 8333; Mailpit on 8025 (web) and 1025 (SMTP).
There are no pre-created users. Create one in the Keycloak admin console (realm `fcp-dev`).

## Licensing
This is proprietary software; all rights reserved. Source files do not carry licence headers.
New third-party dependencies must use a permissive licence (MIT, BSD, Apache-2.0, ISC, PSF, MPL-2.0).
Copyleft licences (GPL, AGPL, SSPL, LGPL in distributed code) require an explicit review recorded in the PR.
Development-only tools that are never distributed (e.g. a local container image) may be used when noted in the PR.
