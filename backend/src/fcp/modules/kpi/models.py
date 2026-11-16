"""KPI definitions (M4-4): versioned reference data, like the financial taxonomy.

A library version (e.g. ``CORE@1.0``) is never changed once released: a changed formula is a new
library version, so a stored KPI value always names the definition version it was computed with
(AC-KP4). Workspace and personal KPIs (M4-5) are tenant data in their own table.
"""

from django.db import models


class KpiDefinition(models.Model):
    class Display(models.TextChoices):
        PERCENT = "percent"  # a ratio shown x 100 with %
        RATIO = "ratio"
        TIMES = "times"
        DAYS = "days"
        MONTHS = "months"
        EUR = "EUR"

    id = models.CharField(primary_key=True, max_length=80)  # "<library>:<key>"
    library = models.CharField(max_length=40)  # "CORE@1.0"
    key = models.CharField(max_length=40)
    name = models.CharField(max_length=120)
    name_el = models.CharField(max_length=120, blank=True)
    category = models.CharField(max_length=20)
    formula = models.TextField()
    display = models.CharField(max_length=10, choices=Display.choices)
    direction = models.CharField(max_length=14)  # HIGHER_BETTER | LOWER_BETTER
    convention = models.CharField(max_length=500)
    nm_note = models.CharField(max_length=300)
    nm_reason = models.CharField(max_length=200, blank=True)
    example = models.CharField(max_length=300)
    order = models.PositiveIntegerField()

    class Meta:
        db_table = "kpi_definition"
        constraints = [
            models.UniqueConstraint(fields=["library", "key"], name="kpi_definition_key"),
        ]
