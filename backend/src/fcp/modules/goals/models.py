"""Goals (M4-6, doc 10 §6).

- ``Goal``: what is tracked for one legal entity: a metric over a window of whole months. It is
  active or retired; nothing else about it changes.
- ``GoalVersion``: the target, its type, the materiality threshold, the owner and the goal-seek
  driver. The **baseline** (the metric's starting value, the date and the calculation run it came
  from) is captured when the goal is created and copied unchanged into every later version
  (AC-GO1). A change of target is a new version; a version's content never changes, and the only
  update is superseding it, once (database trigger).
- ``GoalEvaluation``: an append-only summary of each evaluation run (status, projected outcome,
  gap), read by alerts (M4-7) and for the trend of the gap. The figures themselves are the
  calculation run's results, with lineage.
"""

from django.conf import settings
from django.db import models

from fcp.core.db.models import TenantOwned

USER = settings.AUTH_USER_MODEL
LEGAL_ENTITY = "tenancy.LegalEntity"
DIGITS, PLACES = 50, 28  # as calculation results (ratios unrounded)


class Goal(TenantOwned):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        RETIRED = "RETIRED"

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=120)
    metric = models.CharField(max_length=60)  # "REVENUE", "CASH", "kpi:EBITDA_MARGIN", ...
    metric_kind = models.CharField(max_length=10)  # ADDITIVE | RATIO | BALANCE
    metric_ref = models.CharField(max_length=120)  # the definition version, e.g. CORE@1.0:DSO
    metric_name = models.CharField(max_length=120)
    formula = models.TextField()  # as it was when the goal was created
    metric_direction = models.CharField(max_length=14)  # HIGHER_BETTER | LOWER_BETTER
    unit = models.CharField(max_length=10)  # EUR, ratio, days, ...
    display = models.CharField(max_length=10)  # EUR, percent, ratio, days, times, months
    period_start = models.DateField()  # first day of a month
    period_end = models.DateField()  # last day of a month: the target date
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.ACTIVE)
    created_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    retired_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "goals_goal"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(period_start__lt=models.F("period_end")),
                name="goals_goal_period",
            ),
            models.CheckConstraint(
                condition=models.Q(metric_kind__in=["ADDITIVE", "RATIO", "BALANCE"]),
                name="goals_goal_metric_kind",
            ),
            models.CheckConstraint(
                condition=models.Q(status="ACTIVE", retired_at__isnull=True)
                | models.Q(status="RETIRED", retired_at__isnull=False),
                name="goals_goal_retired",
            ),
        ]


class GoalVersion(TenantOwned):
    class TargetType(models.TextChoices):
        ABSOLUTE = "ABSOLUTE"  # reach a value by the target date
        CHANGE_PCT = "CHANGE_PCT"  # change the baseline by a percentage
        MAINTAIN_MIN = "MAINTAIN_MIN"  # stay at or above a threshold throughout
        MAINTAIN_MAX = "MAINTAIN_MAX"  # stay at or below a threshold throughout

    class Direction(models.TextChoices):
        AT_LEAST = "AT_LEAST"
        AT_MOST = "AT_MOST"

    goal = models.ForeignKey(Goal, on_delete=models.PROTECT, related_name="versions")
    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    number = models.PositiveIntegerField()
    target_type = models.CharField(max_length=12, choices=TargetType.choices)
    target_input = models.DecimalField(
        max_digits=DIGITS, decimal_places=PLACES
    )  # as entered (a change as a fraction: 0.15)
    target_value = models.DecimalField(
        max_digits=DIGITS, decimal_places=PLACES
    )  # the value to reach, in the metric's unit
    direction = models.CharField(max_length=8, choices=Direction.choices)
    materiality = models.DecimalField(max_digits=7, decimal_places=4)  # fraction of the target
    owner = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    driver = models.CharField(max_length=40, blank=True)  # taxonomy key for the generic goal-seek
    # The frozen baseline (AC-GO1): copied unchanged into every version.
    baseline_value = models.DecimalField(
        null=True, blank=True, max_digits=DIGITS, decimal_places=PLACES
    )
    baseline_nm_reason = models.CharField(max_length=200, blank=True)
    baseline_from = models.DateField()
    baseline_to = models.DateField()
    baseline_run_id = models.UUIDField()  # metrics_calc_run, same entity (composite FK)
    reason = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "goals_version"
        constraints = [
            models.UniqueConstraint(fields=["goal", "number"], name="goals_version_number"),
            models.UniqueConstraint(
                fields=["goal"],
                condition=models.Q(superseded_at__isnull=True),
                name="goals_version_one_current",
            ),
            models.CheckConstraint(
                condition=models.Q(number=1) | ~models.Q(reason=""),
                name="goals_version_reason",
            ),
            models.CheckConstraint(
                condition=models.Q(baseline_value__isnull=False, baseline_nm_reason="")
                | (models.Q(baseline_value__isnull=True) & ~models.Q(baseline_nm_reason="")),
                name="goals_version_baseline",
            ),
            models.CheckConstraint(
                condition=models.Q(materiality__gte=0, materiality__lte=1),
                name="goals_version_materiality",
            ),
        ]


class GoalEvaluation(TenantOwned):
    """One evaluation's summary (append-only). The status is on track, at risk, off track, or
    undetermined when the projected value is not meaningful."""

    class Status(models.TextChoices):
        ON_TRACK = "ON_TRACK"
        AT_RISK = "AT_RISK"
        OFF_TRACK = "OFF_TRACK"
        UNDETERMINED = "UNDETERMINED"

    goal = models.ForeignKey(Goal, on_delete=models.PROTECT, related_name="evaluations")
    version = models.ForeignKey(GoalVersion, on_delete=models.PROTECT, related_name="+")
    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    run_id = models.UUIDField()  # metrics_calc_run, same entity (composite FK)
    as_of = models.DateField()
    status = models.CharField(max_length=12, choices=Status.choices)
    projected = models.DecimalField(null=True, blank=True, max_digits=DIGITS, decimal_places=PLACES)
    actual = models.DecimalField(null=True, blank=True, max_digits=DIGITS, decimal_places=PLACES)
    gap = models.DecimalField(
        null=True, blank=True, max_digits=DIGITS, decimal_places=PLACES
    )  # target - projected
    breach_date = models.DateField(null=True, blank=True)  # first forecast breach (thresholds)
    method = models.CharField(max_length=20)  # how the outcome was projected
    created_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "goals_evaluation"
        indexes = [models.Index(fields=["goal", "created_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["ON_TRACK", "AT_RISK", "OFF_TRACK", "UNDETERMINED"]),
                name="goals_evaluation_status",
            ),
        ]
