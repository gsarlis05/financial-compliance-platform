"""The VAT return's boxes and the rules that map each line to them (V1-2b, #213; brief 25).

The rules are versioned data (``data/cy_vat_boxes_v<n>.json``), each with its source; a released
version never changes, a correction is a new version. A line is one of four kinds:

- ``OUTPUT_VAT``: a line on an OUTPUT VAT account (credit positive);
- ``INPUT_VAT``: a line on an INPUT VAT account (debit positive, the deductible VAT);
- ``NET_SALE`` / ``NET_PURCHASE``: a taxable amount on another account carrying the VAT code
  (sales credit positive, purchases debit positive).

For a VAT code's category and a line kind, the rules give the boxes the amount adds to, or say
that the category is excluded (not a supply, a settlement), or that it is not supported (shown as
an exception, never guessed).
"""

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

DATA = Path(__file__).parent / "data"
LineKind = Literal["OUTPUT_VAT", "INPUT_VAT", "NET_SALE", "NET_PURCHASE"]
VAT_BOXES = ("1", "2", "3", "4", "5")
ALL_BOXES = ("1", "2", "3", "4", "5", "6", "7", "8A", "8B", "9", "10", "11A", "11B")


@dataclass(frozen=True)
class Mapping:
    status: Literal["MAPPED", "EXCLUDED", "UNSUPPORTED"]
    boxes: tuple[str, ...]
    reason: str  # the rule's source when mapped; why otherwise


@cache
def ruleset(version: str = "CY-VAT-BOXES@1") -> dict[str, Any]:
    number = version.rsplit("@", 1)[1]
    data: dict[str, Any] = json.loads((DATA / f"cy_vat_boxes_v{number}.json").read_text())
    if data["id"] != version:
        raise ValueError(f"{version} not found")
    return data


def mapping(category: str, kind: LineKind, version: str = "CY-VAT-BOXES@1") -> Mapping:
    rules = ruleset(version)
    for rule in rules["rules"]:
        if (rule["category"], rule["line"]) == (category, kind):
            return Mapping("MAPPED", tuple(rule["boxes"]), rule["source"])
    for rule in rules["excluded"]:
        if rule["category"] == category:
            return Mapping("EXCLUDED", (), rule["reason"])
    for rule in rules["unsupported"]:
        if rule["category"] == category and rule.get("line", kind) == kind:
            return Mapping("UNSUPPORTED", (), rule["reason"])
    return Mapping("UNSUPPORTED", (), f"No rule maps a {kind.lower().replace('_', ' ')} line of "
                   f"category {category or 'none'}.")  # fmt: skip
