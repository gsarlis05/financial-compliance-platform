"""Taxonomy reference data, seeded from ``taxonomy/*.json`` (idempotent upsert by id)."""

import json
from importlib import resources
from typing import Any

TAXONOMIES = ("ifrs_sme_cy_1.0",)
DEFAULT_TAXONOMY = "IFRS_SME_CY@1.0"
DEFAULT_MAPS = {"cy_business": "default_map_cy_business"}


def _load(name: str) -> dict[str, Any]:
    text = resources.files(__package__).joinpath(f"taxonomy/{name}.json").read_text("utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


def default_map(template: str) -> dict[str, str]:
    """Account code -> line code for a chart-of-accounts template (empty if none)."""
    name = DEFAULT_MAPS.get(template)
    return dict(_load(name)["accounts"]) if name else {}


def seed_taxonomies(version_model: Any = None, line_model: Any = None) -> int:
    """Upsert every taxonomy. Migrations pass historical models; at runtime the current ones."""
    if version_model is None or line_model is None:
        from .models import TaxonomyLine, TaxonomyVersion  # noqa: PLC0415

        version_model, line_model = TaxonomyVersion, TaxonomyLine
    count = 0
    for name in TAXONOMIES:
        data = _load(name)
        version_id = f"{data['key']}@{data['semver']}"
        version_model.objects.update_or_create(
            id=version_id,
            defaults={"key": data["key"], "semver": data["semver"], "name": data["name"],
                      "note": data.get("note", "")[:500]},
        )  # fmt: skip
        for row in data["lines"]:
            line_model.objects.update_or_create(
                id=f"{version_id}:{row['code']}",
                defaults={
                    "version_id": version_id, "code": row["code"], "name": row["name"],
                    "name_el": row.get("name_el", ""), "statement": row["statement"],
                    "section": row["section"], "account_types": ",".join(row["account_types"]),
                    "direction": row["direction"], "order": row["order"],
                },
            )  # fmt: skip
            count += 1
    return count
