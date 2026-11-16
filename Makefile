# Local configuration (.env is git-ignored; create it with `make dev-env`).
-include .env
export

.PHONY: help install dev-env dev dev-down dev-reset migrate run-backend run-frontend \
	services synthetic iac-check e2e-login e2e-ui demo openapi openapi-check ops-checks test lint backend-test frontend-test backend-lint frontend-lint security prove-gates

help:
	@echo "make dev           start local services (creates .env, installs deps, migrates)"
	@echo "make run-backend   Django dev server on http://localhost:8000"
	@echo "make run-frontend  Vite dev server on http://localhost:5173"
	@echo "make demo          load the Demo Trading workspace via the API (SHARE_WITH=email to see it in the UI)"
	@echo "make openapi       regenerate docs/api/openapi.json"
	@echo "make synthetic     generate synthetic business + household datasets into var/"
	@echo "make test | lint | security | prove-gates"
	@echo "make dev-down      stop services (data kept); make dev-reset deletes local data"

install:
	cd backend && uv sync --frozen
	cd frontend && pnpm install --frozen-lockfile

dev-env:
	python3 scripts/dev/init_env.py

# `$(MAKE)` re-reads .env after dev-env may have created it.
dev: dev-env install
	$(MAKE) services migrate

services:
	docker compose up -d --wait

dev-down:
	docker compose down

dev-reset:
	docker compose down --volumes

# Synthetic datasets for development (git-ignored var/ directory). ADR-0010: no real data.
synthetic:
	cd backend && uv run python -m fcp.devtools.synthetic business --seed 42 --out ../var/synthetic/business
	cd backend && uv run python -m fcp.devtools.synthetic household --seed 7 --out ../var/synthetic/household

migrate:
	cd backend && DB_ROLE=owner uv run python manage.py migrate --noinput

run-backend:
	cd backend && uv run python manage.py runserver 127.0.0.1:8000

run-frontend:
	cd frontend && pnpm dev

test: backend-test frontend-test

lint: backend-lint frontend-lint

backend-test:
	cd backend && uv run pytest --cov && uv run coverage report --include='*/fcp/core/money/*' --fail-under=100 >/dev/null

frontend-test:
	cd frontend && pnpm test

backend-lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy \
		&& uv run lint-imports && uv run python -m tools.fcp_lint.no_float

frontend-lint:
	cd frontend && pnpm lint && pnpm typecheck

security:
	docker run --rm -v "$$PWD:/src" -w /src semgrep/semgrep:1.183.0 semgrep scan --config .semgrep/ --error --metrics=off backend/src backend/tools
	docker run --rm -v "$$PWD:/repo" zricethezav/gitleaks:v8.30.1 git /repo --no-banner -c /repo/.gitleaks.toml --redact

prove-gates:
	scripts/ci/prove-gates.sh

# Static checks only. Needs Docker and access to the Terraform registry (or TF_CLI_CONFIG_FILE
# pointing at a provider mirror). Nothing is ever planned against or applied to an account.
iac-check:
	docker run --rm -v "$$PWD:/repo" hashicorp/terraform:1.17.1 -chdir=/repo/infra/terraform fmt -check -recursive
	docker run --rm -v "$$PWD:/repo" hashicorp/terraform:1.17.1 -chdir=/repo/infra/terraform/envs/staging init -backend=false -input=false -lockfile=readonly
	docker run --rm -v "$$PWD:/repo" hashicorp/terraform:1.17.1 -chdir=/repo/infra/terraform/envs/staging validate
	docker run --rm -v "$$PWD/infra/terraform:/tf" bridgecrew/checkov:3.4.3 -d /tf --framework terraform --quiet --compact --skip-path .terraform

# Live MFA sign-in check against the local stack (needs `make dev` and `make run-backend`).
e2e-login:
	scripts/e2e/keycloak-mfa-login.sh

# Browser smoke test of the web UI (needs make services, run-backend and run-frontend; resets nothing).
e2e-ui:
	node scripts/e2e/ui-smoke.js

# AC-G5 demo: a new "Demo Trading" workspace with one synthetic year (local dev only).
demo:
	cd backend && uv run python -m fcp.devtools.demo $(if $(SHARE_WITH),--share-with $(SHARE_WITH),)

openapi:
	cd backend && uv run python -m fcp.openapi ../docs/api/openapi.json

openapi-check:
	cd backend && uv run python -m fcp.openapi --check ../docs/api/openapi.json

# Nightly operational checks (audit chains and ledger integrity for every workspace).
ops-checks:
	cd backend && DB_ROLE=owner uv run python manage.py audit_verify
	cd backend && DB_ROLE=owner uv run python manage.py ledger_integrity_check
