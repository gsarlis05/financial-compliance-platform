"""AC-G3: the published OpenAPI document matches the code."""

import importlib
import json
import pkgutil
from pathlib import Path

from ninja import Schema

import fcp.modules
from fcp import openapi

PUBLISHED = Path(__file__).resolve().parents[3] / "docs" / "api" / "openapi.json"


def test_published_document_is_current() -> None:
    assert PUBLISHED.read_text(encoding="utf-8") == openapi.render()


def test_money_is_a_string_and_operation_ids_are_unique() -> None:
    schema = json.loads(openapi.render())
    line = schema["components"]["schemas"]["LineIn"]["properties"]
    assert line["debit"]["type"] == "string"
    ids = [op["operationId"] for path in schema["paths"].values() for op in path.values()]
    assert len(ids) == len(set(ids))


def test_schema_names_are_unique_across_modules() -> None:
    """Django Ninja names components by class name, so two modules' ``LineOut`` would silently
    publish one shape for both."""
    owners: dict[str, set[str]] = {}
    for info in pkgutil.iter_modules(fcp.modules.__path__):
        module = importlib.import_module(f"fcp.modules.{info.name}.api")
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and issubclass(value, Schema)
                and value.__module__ == module.__name__
            ):
                owners.setdefault(value.__name__, set()).add(info.name)
    assert {name: mods for name, mods in owners.items() if len(mods) > 1} == {}


def test_cli_writes_and_checks(tmp_path: Path) -> None:
    target = tmp_path / "api" / "openapi.json"
    assert openapi.main(["--check", str(target)]) == 1
    assert openapi.main([str(target)]) == 0
    assert openapi.main(["--check", str(target)]) == 0
    target.write_text("{}", encoding="utf-8")
    assert openapi.main(["--check", str(target)]) == 1
