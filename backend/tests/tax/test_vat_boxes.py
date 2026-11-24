"""The VAT return's box rules (V1-2b, #213): the owner's specification's mapping matrix (brief 25
§2) as versioned data, every catalogue category accounted for, nothing guessed."""

from pathlib import Path
from typing import Any, cast

import pytest

from fcp.modules.ledger.vat import catalogue_rows
from fcp.modules.tax.boxes import ALL_BOXES, LineKind, mapping, ruleset

pytestmark = pytest.mark.django_db
KINDS = ("OUTPUT_VAT", "INPUT_VAT", "NET_SALE", "NET_PURCHASE")


def boxes(category: str, kind: Any) -> tuple[str, ...]:
    found = mapping(category, kind)
    assert found.status == "MAPPED", (category, kind, found)
    return found.boxes


def test_the_specification_matrix() -> None:
    """Brief 25 §2, row by row: VAT boxes and net-value boxes."""
    assert (boxes("DOMESTIC", "OUTPUT_VAT"), boxes("DOMESTIC", "NET_SALE")) == (("1",), ("6",))
    purchase = (boxes("DOMESTIC", "INPUT_VAT"), boxes("DOMESTIC", "NET_PURCHASE"))
    assert purchase == (("4",), ("7",))
    assert boxes("EU_GOODS_ACQUISITION", "OUTPUT_VAT") == ("2",)
    assert boxes("EU_GOODS_ACQUISITION", "INPUT_VAT") == ("4",)
    assert boxes("EU_GOODS_ACQUISITION", "NET_PURCHASE") == ("7", "11A")
    reverse_charges = (("RC_EU_SERVICES", ("6", "7", "11B")),
                       ("RC_NON_EU_SERVICES", ("6", "7")), ("RC_DOMESTIC", ("6", "7")))  # fmt: skip
    for category, net in reverse_charges:
        assert boxes(category, "OUTPUT_VAT") == ("1",)
        assert boxes(category, "INPUT_VAT") == ("4",)
        assert boxes(category, "NET_PURCHASE") == net
    assert boxes("EU_GOODS_SUPPLY", "NET_SALE") == ("6", "8A")
    assert boxes("EU_SERVICES_SUPPLY", "NET_SALE") == ("6", "8B")
    assert boxes("ZERO_RATED", "NET_SALE") == ("6", "9")
    assert boxes("OUTSIDE_SCOPE_DEDUCTIBLE", "NET_SALE") == ("6", "10")
    assert boxes("IMPORT", "INPUT_VAT") == ("4",)


def test_nothing_is_guessed() -> None:
    assert mapping("NON_SUPPLY", "NET_PURCHASE").status == "EXCLUDED"
    assert mapping("SETTLEMENT", "OUTPUT_VAT").status == "EXCLUDED"
    for category, kind in (("EXEMPT", "NET_SALE"), ("EXEMPT", "NET_PURCHASE"),
                           ("IMPORT", "NET_PURCHASE"), ("LEGACY_REVERSE_CHARGE", "OUTPUT_VAT"),
                           ("ZERO_RATED", "NET_PURCHASE"), ("EU_GOODS_SUPPLY", "OUTPUT_VAT"),
                           ("", "NET_SALE")):  # fmt: skip
        found = mapping(category, cast(Any, kind))
        assert found.status == "UNSUPPORTED", (category, kind)
        assert found.reason


def test_the_data_is_complete_and_sourced() -> None:
    rules = ruleset()
    assert rules["status"] == "PENDING_PROFESSIONAL_VERIFICATION"
    assert [b["box"] for b in rules["boxes"]] == list(ALL_BOXES)
    assert all(r["source"] for r in rules["rules"])
    assert all(set(r["boxes"]) <= set(ALL_BOXES) for r in rules["rules"])
    keys = {(r["category"], r["line"]) for r in rules["rules"]}
    assert len(keys) == len(rules["rules"])  # one rule per category and line kind
    # Every category the catalogue uses is mapped, excluded or declared unsupported.
    known = ({r["category"] for r in rules["rules"]} | {r["category"] for r in rules["excluded"]}
             | {r["category"] for r in rules["unsupported"]})  # fmt: skip
    categories = {row["category"] for row in catalogue_rows()}
    assert "" not in categories
    assert categories <= known, categories - known
    codes = {row["code"]: row for row in catalogue_rows()}
    assert {"R3", "EUGS", "EUSS", "OSD", "EUGA19", "RCEU19", "RCNEU19", "RCDOM19", "IMP19"} <= set(
        codes
    )
    assert codes["R3"]["rate"] == "0.03"
    assert all(not row["verified"] for row in codes.values())


def test_the_coverage_matrix_matches_the_rules() -> None:
    """``docs/vat/coverage.md`` (V1-2e) shows each category's boxes exactly as the rules do, and
    names every category as supported, excluded or not supported."""
    page = (Path(__file__).parents[3] / "docs" / "vat" / "coverage.md").read_text()
    kinds: tuple[LineKind, ...] = ("OUTPUT_VAT", "INPUT_VAT", "NET_SALE", "NET_PURCHASE")
    shown: dict[str, list[str]] = {}
    for line in page.splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 6 and cells[0].isupper() and cells[0].replace("_", "").isalpha():
            shown[cells[0]] = cells[1:5]
    for category, cells in shown.items():
        for kind, cell in zip(kinds, cells, strict=True):
            found = mapping(category, kind)
            expected = ", ".join(found.boxes) if found.status == "MAPPED" else "not in a box"
            assert cell == expected, (category, kind)
    rules = ruleset()
    mapped = {r["category"] for r in rules["rules"]}
    assert set(shown) == mapped
    for rule in rules["excluded"] + rules["unsupported"]:
        assert rule["category"] in page
