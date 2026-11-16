"""KPI library reference data, seeded from ``library/*.json`` (idempotent upsert by id)."""

import json
from importlib import resources
from typing import Any

LIBRARIES = ("core_1.0",)
DEFAULT_LIBRARY = "CORE@1.0"


def _load(name: str) -> dict[str, Any]:
    text = resources.files(__package__).joinpath(f"library/{name}.json").read_text("utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


def seed_libraries(model: Any = None) -> int:
    """Upsert every library. Migrations pass the historical model; at runtime the current one."""
    if model is None:
        from .models import KpiDefinition  # noqa: PLC0415

        model = KpiDefinition
    count = 0
    for name in LIBRARIES:
        data = _load(name)
        library = f"{data['key']}@{data['semver']}"
        for row in data["kpis"]:
            model.objects.update_or_create(
                id=f"{library}:{row['key']}",
                defaults={
                    "library": library,
                    **{
                        k: row[k]
                        for k in (
                            "key",
                            "name",
                            "name_el",
                            "category",
                            "formula",
                            "display",
                            "direction",
                            "convention",
                            "nm_note",
                            "nm_reason",
                            "example",
                            "order",
                        )
                    },
                },
            )
            count += 1
    return count
