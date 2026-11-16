"""In-app alerts (M4-7, doc 10 §6.2 item 8 and §7, AC-GO4).

- ``AlertState``: the last observed state of one alert key, e.g. ``goal:<id>:status`` is
  ``AT_RISK``. An alert is raised only when the state **changes** into an alerting state, so the
  same condition is never raised twice in a row (de-duplication by key).
- ``Alert``: one raised alert, kept for good. The only change allowed is its acknowledgement, once
  (database trigger); nothing is deleted.
"""

from django.conf import settings
from django.db import models

from fcp.core.db.models import TenantOwned

USER = settings.AUTH_USER_MODEL
LEGAL_ENTITY = "tenancy.LegalEntity"


class AlertState(TenantOwned):
    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    key = models.CharField(max_length=200)
    state = models.CharField(max_length=40)
    changes = models.PositiveIntegerField(default=0)  # how many times the state changed
    changed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "dashboards_alert_state"
        constraints = [
            models.UniqueConstraint(fields=["legal_entity", "key"], name="dashboards_state_key"),
        ]


class Alert(TenantOwned):
    class Kind(models.TextChoices):
        GOAL_STATUS = "GOAL_STATUS"  # a goal became at risk or off track
        GOAL_BREACH = "GOAL_BREACH"  # a goal's threshold is breached, in actuals or forecast
        BUDGET_OVERRUN = "BUDGET_OVERRUN"  # year to date, beyond the variance thresholds
        BUDGET_TREND = "BUDGET_TREND"  # 3 consecutive unfavourable months

    class Severity(models.TextChoices):
        WARNING = "WARNING"
        CRITICAL = "CRITICAL"

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    key = models.CharField(max_length=200)
    sequence = models.PositiveIntegerField()  # the AlertState change that raised it
    kind = models.CharField(max_length=20, choices=Kind.choices)
    state = models.CharField(max_length=40)
    severity = models.CharField(max_length=8, choices=Severity.choices)
    title = models.CharField(max_length=200)
    detail = models.CharField(max_length=500)
    subject_type = models.CharField(max_length=20)  # goal | budget
    subject_id = models.UUIDField()
    period = models.DateField(null=True, blank=True)
    source_run_id = models.UUIDField(null=True, blank=True)  # the calculation run behind it
    audience = models.CharField(max_length=40)  # the permission needed to see it
    acknowledged_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledgement_note = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "dashboards_alert"
        indexes = [models.Index(fields=["legal_entity", "created_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "key", "sequence"], name="dashboards_alert_once"
            ),
            models.CheckConstraint(
                condition=models.Q(acknowledged_by__isnull=True, acknowledged_at__isnull=True)
                | models.Q(acknowledged_by__isnull=False, acknowledged_at__isnull=False),
                name="dashboards_alert_acknowledged",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    kind__in=["GOAL_STATUS", "GOAL_BREACH", "BUDGET_OVERRUN", "BUDGET_TREND"]
                ),
                name="dashboards_alert_kind",
            ),
        ]


class DashboardLayout(TenantOwned):
    """Which widgets a user's dashboard shows, in order, with their options (M4-8). The row
    without a user is the entity's default, used by everyone who has not saved their own."""

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    user = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    widgets = models.JSONField(default=list)  # [{"type": "kpis", "kpis": ["DSO", ...]}, ...]
    updated_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "dashboards_layout"
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "user"], name="dashboards_layout_once",
                nulls_distinct=False,
            ),
        ]  # fmt: skip
