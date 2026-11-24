"""Detect binary floating-point usage in domain code (ADR-0003).

Flags float literals (``1.5``, ``1e3``), calls to ``float(...)`` and ``float`` type annotations.
A line ending in ``# fcp-lint: allow-float (<reason>)`` is exempt: only for values that are not
amounts, such as page layout in PDF exports, where the library requires floats. The reason is
mandatory, so every exemption is visible and justified in review.
Run as ``python -m tools.fcp_lint.no_float <paths>``; exit code 1 when anything is found.
"""

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Domain code: every module plus the shared kernel. Settings and devtools are excluded.
DOMAIN_PATHS = ("src/fcp/core", "src/fcp/modules")


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    message: str


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.findings: list[Finding] = []

    def _add(self, node: ast.AST, message: str) -> None:
        self.findings.append(Finding(self.path, getattr(node, "lineno", 0), message))

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, float):
            self._add(node, f"float literal {node.value!r}; use Decimal('...') or Money")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == "float":
            self._add(node, "call to float(); use Decimal or Money")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        # Catches annotations such as `x: float` and `-> float`, and other references to float.
        if node.id == "float" and isinstance(node.ctx, ast.Load):
            self._add(node, "reference to the float type; use Decimal or Money")
        self.generic_visit(node)


ALLOW = re.compile(r"#\s*fcp-lint:\s*allow-float\s*\(\s*\S[^)]*\)")


def check_source(source: str, path: str = "<string>") -> list[Finding]:
    visitor = _Visitor(path)
    visitor.visit(ast.parse(source, filename=path))
    lines = source.splitlines()
    allowed = {n for n, text in enumerate(lines, start=1) if ALLOW.search(text)}
    # A float() call is also a Name reference; report each line/message once.
    return sorted({f for f in visitor.findings if f.line not in allowed})


def check_paths(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for root in paths:
        files = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for file in files:
            findings.extend(check_source(file.read_text(encoding="utf-8"), str(file)))
    return findings


def main(argv: list[str]) -> int:
    paths = [Path(p) for p in (argv or DOMAIN_PATHS)]
    findings = check_paths(paths)
    for f in findings:
        print(f"{f.path}:{f.line}: {f.message}")  # noqa: T201 - CLI output
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
