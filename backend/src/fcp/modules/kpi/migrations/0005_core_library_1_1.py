"""Seed CORE@1.1 (M7-6): the 19 KPIs of CORE@1.0 unchanged, plus net debt / EBITDA, DSCR,
receivables turnover and inventory turnover. CORE@1.0 stays, so earlier KPI sets keep their
definitions. The runtime role may only read definitions (registry)."""

from typing import Any

from django.db import migrations


def seed(apps: Any, schema_editor: Any) -> None:
    del schema_editor
    from fcp.modules.kpi.library import seed_libraries  # noqa: PLC0415

    seed_libraries(apps.get_model("kpi", "KpiDefinition"))


class Migration(migrations.Migration):
    dependencies = [("kpi", "0004_custom_isolation_and_guards")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
