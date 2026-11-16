#!/usr/bin/env bash
# Prove that each custom CI gate actually fails on a deliberate violation (AC-M0-2).
# Violations are generated in temporary directories at run time and never committed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
GITLEAKS_IMAGE="${GITLEAKS_IMAGE:-zricethezav/gitleaks:v8.30.1}"
SEMGREP_IMAGE="${SEMGREP_IMAGE:-semgrep/semgrep:1.183.0}"
failures=0

expect_failure() {
  local name="$1"; shift
  if "$@" >"$WORK/out.log" 2>&1; then
    echo "GATE NOT PROVEN: '$name' passed on a deliberate violation"; cat "$WORK/out.log"
    failures=$((failures + 1))
  else
    echo "ok: '$name' rejects a deliberate violation"
  fi
}

# 1. Secret scanning: a fake AWS access key generated now.
mkdir -p "$WORK/secrets"
key="AKIA$(python3 -c 'import secrets; print("".join(secrets.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567") for _ in range(16)))')"
printf 'aws_access_key_id = %s\n' "$key" >"$WORK/secrets/config.ini"
expect_failure "gitleaks" docker run --rm -v "$WORK/secrets:/scan:ro" "$GITLEAKS_IMAGE" dir /scan --no-banner

# 2. Module boundaries: tax imports ledger internals instead of ledger.api.
cp -r "$ROOT/backend/src" "$ROOT/backend/tools" "$ROOT/backend/pyproject.toml" "$WORK/"
mkdir -p "$WORK/src/fcp/modules/ledger"
printf '"""Fixture."""\n' >"$WORK/src/fcp/modules/ledger/models.py"
printf 'from fcp.modules.ledger import models  # noqa\n' >>"$WORK/src/fcp/modules/tax/api.py"
expect_failure "import-linter" env -C "$WORK" PYTHONPATH="$WORK/src:$WORK" \
  uv run --project "$ROOT/backend" --no-sync lint-imports --no-cache

# 3. No floating point in domain code.
printf 'RATE = 0.15\n' >"$WORK/float_fixture.py"
expect_failure "no-float" env -C "$ROOT/backend" \
  uv run --no-sync python -m tools.fcp_lint.no_float "$WORK/float_fixture.py"

# 4. Semgrep rules: annotated fixtures must match exactly (ruleid/ok comments).
if docker run --rm -v "$ROOT:/src" -w /src "$SEMGREP_IMAGE" semgrep --test --metrics=off \
  --config .semgrep/python.yaml .semgrep/python.py >"$WORK/out.log" 2>&1 \
  && grep -q "All tests passed" "$WORK/out.log"; then
  echo "ok: 'semgrep' rule fixtures match"
else
  echo "GATE NOT PROVEN: semgrep rule tests failed"; cat "$WORK/out.log"; failures=$((failures + 1))
fi

if [ "$failures" -gt 0 ]; then
  echo "$failures gate(s) not proven"; exit 1
fi
echo "All gates proven."
