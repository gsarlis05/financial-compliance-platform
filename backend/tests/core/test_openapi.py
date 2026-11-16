"""AC-G3: the published OpenAPI document matches the code."""

import json
from pathlib import Path

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


def test_cli_writes_and_checks(tmp_path: Path) -> None:
    target = tmp_path / "api" / "openapi.json"
    assert openapi.main(["--check", str(target)]) == 1
    assert openapi.main([str(target)]) == 0
    assert openapi.main(["--check", str(target)]) == 0
    target.write_text("{}", encoding="utf-8")
    assert openapi.main(["--check", str(target)]) == 1
