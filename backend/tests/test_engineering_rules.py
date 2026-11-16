"""Tests proving the custom engineering-rule checkers work, and that the codebase obeys them."""

from pathlib import Path

import grimp
import pytest

from tools.fcp_lint.importlinter_contracts import find_violations
from tools.fcp_lint.no_float import DOMAIN_PATHS, check_paths, check_source

BACKEND = Path(__file__).resolve().parent.parent


# --- no-float rule ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "x = 0.1",
        "x = 1e3",
        "x = float('1.0')",
        "def f(a: float) -> None: ...",
        "def f() -> float: ...",
        "x: list[float] = []",
    ],
)
def test_no_float_checker_flags_float_usage(source: str) -> None:
    assert check_source(source), f"expected a finding for {source!r}"


@pytest.mark.parametrize(
    "source",
    [
        "from decimal import Decimal\nx = Decimal('0.1')",
        "x = 10",
        "s = 'float 1.5 in a string is fine'",
        "# 1.5 in a comment is fine",
    ],
)
def test_no_float_checker_allows_decimal_code(source: str) -> None:
    assert check_source(source) == []


def test_domain_code_contains_no_float() -> None:
    findings = check_paths([BACKEND / p for p in DOMAIN_PATHS])
    assert findings == [], "\n".join(f"{f.path}:{f.line}: {f.message}" for f in findings)


# --- public-API import contract --------------------------------------------------------------


def _graph(*imports: tuple[str, str]) -> grimp.ImportGraph:
    graph = grimp.ImportGraph()
    for importer, imported in imports:
        graph.add_module(importer)
        graph.add_module(imported)
        graph.add_import(importer=importer, imported=imported, line_number=1, line_contents="x")
    return graph


def test_import_via_public_api_is_allowed() -> None:
    graph = _graph(("fcp.modules.cashflow.engine", "fcp.modules.reporting.api"))
    assert find_violations(graph, "fcp.modules", "api") == []


def test_import_within_same_module_is_allowed() -> None:
    graph = _graph(("fcp.modules.ledger.api", "fcp.modules.ledger.posting"))
    assert find_violations(graph, "fcp.modules", "api") == []


@pytest.mark.parametrize(
    "imported",
    ["fcp.modules.ledger.models", "fcp.modules.ledger", "fcp.modules.ledger.api_helpers"],
)
def test_import_bypassing_public_api_is_a_violation(imported: str) -> None:
    graph = _graph(("fcp.modules.tax.compute", imported))
    violations = find_violations(graph, "fcp.modules", "api")
    assert [v.imported for v in violations] == [imported]


def test_imports_outside_modules_root_are_ignored() -> None:
    graph = _graph(("fcp.core.money", "decimal"), ("fcp.urls", "fcp.modules.ledger.models"))
    assert find_violations(graph, "fcp.modules", "api") == []
