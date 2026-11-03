.PHONY: test lint backend-test frontend-test backend-lint frontend-lint install

install:
	cd backend && uv sync --frozen
	cd frontend && pnpm install --frozen-lockfile

test: backend-test frontend-test

lint: backend-lint frontend-lint

backend-test:
	cd backend && uv run pytest

frontend-test:
	cd frontend && pnpm test

backend-lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src tests

frontend-lint:
	cd frontend && pnpm lint && pnpm typecheck
