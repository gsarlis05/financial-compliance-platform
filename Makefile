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
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run lint-imports && uv run python -m tools.fcp_lint.no_float

frontend-lint:
	cd frontend && pnpm lint && pnpm typecheck

.PHONY: security prove-gates
security:
	docker run --rm -v "$$PWD:/src" -w /src semgrep/semgrep:1.183.0 semgrep scan --config .semgrep/ --error --metrics=off backend/src backend/tools
	docker run --rm -v "$$PWD:/repo" zricethezav/gitleaks:v8.30.1 git /repo --no-banner -c /repo/.gitleaks.toml --redact

prove-gates:
	scripts/ci/prove-gates.sh
