"""Custom import-linter contract: modules may import each other only via their public API.

Rule (docs/planning/02-software-architecture.md section 2): code in ``fcp.modules.<a>`` may
import from ``fcp.modules.<b>`` (a != b) only through ``fcp.modules.<b>.api``.
"""

from dataclasses import dataclass

from grimp import ImportGraph
from importlinter import Contract, ContractCheck, fields
from importlinter.application import output


@dataclass(frozen=True, order=True)
class Violation:
    importer: str
    imported: str
    line_number: int
    line_contents: str


def _owning_module(name: str, root: str) -> str | None:
    """Return the top-level module package under ``root`` that ``name`` belongs to."""
    prefix = root + "."
    if not name.startswith(prefix):
        return None
    return prefix + name[len(prefix) :].split(".", 1)[0]


def find_violations(graph: ImportGraph, root: str, public_name: str) -> list[Violation]:
    """Find direct imports across module boundaries that bypass the public API module."""
    violations: list[Violation] = []
    for importer in sorted(graph.modules):
        importer_owner = _owning_module(importer, root)
        if importer_owner is None:
            continue
        for imported in sorted(graph.find_modules_directly_imported_by(importer)):
            imported_owner = _owning_module(imported, root)
            if imported_owner is None or imported_owner == importer_owner:
                continue
            if imported == f"{imported_owner}.{public_name}":
                continue
            details = graph.get_import_details(importer=importer, imported=imported)
            if not details:
                violations.append(Violation(importer, imported, 0, ""))
            violations.extend(
                Violation(importer, imported, d["line_number"], d["line_contents"]) for d in details
            )
    return violations


class PublicApiContract(Contract):
    """Modules under ``modules_root`` import each other only via ``<module>.<public_module>``."""

    type_name = "public_api"

    modules_root = fields.StringField()
    public_module = fields.StringField(default="api")

    def check(self, graph: ImportGraph, verbose: bool) -> ContractCheck:
        violations = find_violations(graph, str(self.modules_root), str(self.public_module))
        return ContractCheck(kept=not violations, metadata={"violations": violations})

    def render_broken_contract(self, check: ContractCheck) -> None:
        for v in check.metadata["violations"]:
            output.print_error(
                f"{v.importer} imports {v.imported} (line {v.line_number}: {v.line_contents!r}); "
                f"import from the module's public '{self.public_module}' module instead.",
                bold=False,
            )
            output.new_line()
