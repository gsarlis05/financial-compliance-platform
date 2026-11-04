"""Seed the core KPI library (CORE@1.0, M4-4). The runtime role may only read it (registry)."""

from typing import Any

from django.db import migrations


def seed(apps: Any, schema_editor: Any) -> None:
    del schema_editor
    from fcp.modules.kpi.library import seed_libraries  # noqa: PLC0415

    seed_libraries(apps.get_model("kpi", "KpiDefinition"))


class Migration(migrations.Migration):
    dependencies = [("kpi", "0001_definitions")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
