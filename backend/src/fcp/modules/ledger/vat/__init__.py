"""VAT code catalogue: reference data per jurisdiction, seeded from ``<jurisdiction>.json``.

``seed_catalogue`` is idempotent (update or create by id) and is run by migration 0014 and by the
``seed_reference_data`` management command. Codes are never deleted: posted lines reference them.
"""

import json
from importlib import resources
from typing import Any

JURISDICTIONS = ("cy",)


def code_id(jurisdiction: str, code: str, valid_from: str | None) -> str:
    return f"{jurisdiction}:{code}:{valid_from or 'open'}"


def catalogue_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in JURISDICTIONS:
        text = resources.files(__package__).joinpath(f"{name}.json").read_text(encoding="utf-8")
        data = json.loads(text)
        for row in data["codes"]:
            rows.append(
                {
                    "id": code_id(data["jurisdiction"], row["code"], row.get("valid_from")),
                    "jurisdiction": data["jurisdiction"],
                    "code": row["code"],
                    "name": row["name"],
                    "name_el": row.get("name_el", ""),
                    "treatment": row["treatment"],
                    "rate": row.get("rate"),
                    "valid_from": row.get("valid_from"),
                    "valid_to": row.get("valid_to"),
                    "verified": row.get("verified", False),
                    "verification_note": row.get("verification_note", data["note"])[:500],
                }
            )
    return rows


def seed_catalogue(model: Any) -> int:
    """Upsert every catalogue row into ``model`` (the VatCode model, current or historical)."""
    for row in catalogue_rows():
        model.objects.update_or_create(id=row.pop("id"), defaults=row)
    return len(catalogue_rows())
