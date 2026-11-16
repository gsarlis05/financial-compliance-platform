"""KPI definitions (M4-4): versioned reference data, like the financial taxonomy.

A library version (e.g. ``CORE@1.0``) is never changed once released: a changed formula is a new
library version, so a stored KPI value always names the definition version it was computed with
(AC-KP4). Workspace and personal KPIs, and operational metrics (M4-5), are tenant data below.
"""

from django.conf import settings
from django.db import models

from fcp.core.db.models import TenantOwned


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


# --- custom KPIs and operational metrics (M4-5, tenant data) ------------------------------------

USER = settings.AUTH_USER_MODEL
LEGAL_ENTITY = "tenancy.LegalEntity"


class CustomKpi(TenantOwned):
    """One version of a custom KPI. PERSONAL KPIs are visible to their owner only and are ACTIVE at
    once; WORKSPACE KPIs are SUBMITTED and need approval by someone else (AC-KP4). A change is a
    new version; a version's content never changes (database trigger)."""

    class Scope(models.TextChoices):
        PERSONAL = "PERSONAL"
        WORKSPACE = "WORKSPACE"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"  # personal, in use
        SUBMITTED = "SUBMITTED"  # workspace, waiting for approval
        APPROVED = "APPROVED"  # workspace, in use
        REJECTED = "REJECTED"
        SUPERSEDED = "SUPERSEDED"
        RETIRED = "RETIRED"

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    key = models.CharField(max_length=40)
    version = models.PositiveIntegerField()
    scope = models.CharField(max_length=10, choices=Scope.choices)
    owner = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=120)
    formula = models.TextField()
    unit = models.CharField(max_length=10)  # the formula's unit, from checking it
    display = models.CharField(max_length=10, choices=KpiDefinition.Display.choices)
    direction = models.CharField(max_length=14)
    convention = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices)
    supersedes = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_comment = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "kpi_custom"
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "key", "version"], name="kpi_custom_version"
            ),
            models.CheckConstraint(
                condition=models.Q(direction__in=["HIGHER_BETTER", "LOWER_BETTER"]),
                name="kpi_custom_direction",
            ),
            # A workspace KPI is never decided by its author (segregation of duties).
            models.CheckConstraint(
                condition=~models.Q(scope="WORKSPACE", status__in=["APPROVED", "REJECTED"])
                | ~models.Q(decided_by=models.F("owner")),
                name="kpi_custom_sod",
            ),
            models.CheckConstraint(
                condition=models.Q(scope="PERSONAL", status__in=["ACTIVE", "SUPERSEDED", "RETIRED"])
                | models.Q(
                    scope="WORKSPACE",
                    status__in=["SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED", "RETIRED"],
                ),
                name="kpi_custom_status",
            ),
        ]


class OperationalMetric(TenantOwned):
    """A non-ledger metric (customers, headcount, units sold, MRR) entered by hand (doc 10 §5.3).
    LAST metrics are point values (the period's last month counts); SUM metrics add up."""

    class Unit(models.TextChoices):
        COUNT = "count"
        EUR = "EUR"

    class Aggregation(models.TextChoices):
        LAST = "LAST"
        SUM = "SUM"

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    key = models.CharField(max_length=40)
    name = models.CharField(max_length=120)
    unit = models.CharField(max_length=5, choices=Unit.choices)
    aggregation = models.CharField(max_length=4, choices=Aggregation.choices)
    created_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "kpi_operational_metric"
        constraints = [
            models.UniqueConstraint(fields=["legal_entity", "key"], name="kpi_operational_key"),
        ]


class OperationalValue(TenantOwned):
    """One month's value of an operational metric. Values are versioned: a correction supersedes
    the current version, which is kept (source MANUAL, nature ACTUAL, never ledger data)."""

    metric = models.ForeignKey(OperationalMetric, on_delete=models.PROTECT, related_name="values")
    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    month = models.DateField()
    value = models.DecimalField(max_digits=19, decimal_places=4)
    version = models.PositiveIntegerField()
    note = models.CharField(max_length=300, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "kpi_operational_value"
        constraints = [
            models.UniqueConstraint(
                fields=["metric", "month", "version"], name="kpi_operational_value_version"
            ),
            models.UniqueConstraint(
                fields=["metric", "month"],
                condition=models.Q(superseded_at__isnull=True),
                name="kpi_operational_value_current",
            ),
        ]
