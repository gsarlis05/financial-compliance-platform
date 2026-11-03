# Local configuration (.env is git-ignored; create it with `make dev-env`).
-include .env
export

.PHONY: help install dev-env dev dev-down dev-reset migrate run-backend run-frontend \
	services test lint backend-test frontend-test backend-lint frontend-lint security prove-gates

help:
	@echo "make dev           start local services (creates .env, installs deps, migrates)"
	@echo "make run-backend   Django dev server on http://localhost:8000"
	@echo "make run-frontend  Vite dev server on http://localhost:5173"
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

migrate:
	cd backend && uv run python manage.py migrate --noinput

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
