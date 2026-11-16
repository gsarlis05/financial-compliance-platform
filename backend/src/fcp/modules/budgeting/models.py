"""Budgets, versions and lines (M4-1).

- ``Budget``: one entity, one fiscal year, a type (annual, departmental, project). Departmental and
  project budgets name a dimension value.
- ``BudgetVersion``: the lifecycle DRAFT → SUBMITTED → APPROVED → LOCKED, plus SUPERSEDED. A
  revision is a new version with a reason that ``supersedes`` the version it revises. Content is
  fixed once submitted, and only the documented status changes are allowed (database triggers).
- ``BudgetLine``: a taxonomy line or an account, optionally with a dimension value, and how it was
  phased. ``BudgetAmount``: its value for one month, always of nature BUDGET (doc 10 P2).
- ``BudgetEvent``: the approval trail (append-only).
- ``BudgetSettings``: per entity, whether segregation of duties applies to approvals.

Amounts are positive in the line's natural direction (revenue as income, costs as cost).
"""

from django.conf import settings
from django.db import models

from fcp.core.db.models import TenantOwned

LEGAL_ENTITY = "tenancy.LegalEntity"
USER = settings.AUTH_USER_MODEL


class BudgetSettings(TenantOwned):
    legal_entity = models.OneToOneField(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    sod_required = models.BooleanField(
        default=True, help_text="The person who submitted a version cannot approve it"
    )
    # A variance needs an explanation when both thresholds are reached (M4-3, AC-BU5).
    explain_above_amount = models.DecimalField(max_digits=19, decimal_places=2, default=1000)
    explain_above_percent = models.DecimalField(max_digits=7, decimal_places=2, default=10)
    updated_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "budgeting_settings"


class Budget(TenantOwned):
    class Kind(models.TextChoices):
        ANNUAL = "ANNUAL"
        DEPARTMENTAL = "DEPARTMENTAL"
        PROJECT = "PROJECT"

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    fiscal_year_id = models.UUIDField()  # ledger_fiscal_year, same entity (composite FK)
    fiscal_year_start = models.DateField()
    fiscal_year_end = models.DateField()
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    dimension_value_id = models.UUIDField(null=True, blank=True)  # ledger_dimension_value
    created_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "budgeting_budget"
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "fiscal_year_id", "name"], name="budgeting_budget_name"
            ),
            models.CheckConstraint(
                condition=models.Q(kind="ANNUAL", dimension_value_id__isnull=True)
                | (~models.Q(kind="ANNUAL") & models.Q(dimension_value_id__isnull=False)),
                name="budgeting_budget_scope",
            ),
            models.CheckConstraint(
                condition=models.Q(fiscal_year_start__lt=models.F("fiscal_year_end")),
                name="budgeting_budget_dates",
            ),
        ]


class BudgetVersion(TenantOwned):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        SUBMITTED = "SUBMITTED"
        APPROVED = "APPROVED"
        LOCKED = "LOCKED"
        SUPERSEDED = "SUPERSEDED"

    budget = models.ForeignKey(Budget, on_delete=models.PROTECT, related_name="versions")
    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    supersedes = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reason = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    content_hash = models.CharField(max_length=64, blank=True)  # set on submission
    submitted_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    sod_applied = models.BooleanField(null=True, blank=True)
    locked_by = models.ForeignKey(
        USER, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    locked_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "budgeting_version"
        constraints = [
            models.UniqueConstraint(fields=["budget", "number"], name="budgeting_version_number"),
            models.UniqueConstraint(
                fields=["budget"],
                condition=models.Q(status__in=["DRAFT", "SUBMITTED"]),
                name="budgeting_version_one_open",
            ),
            models.CheckConstraint(
                condition=models.Q(number=1, supersedes__isnull=True)
                | models.Q(number__gt=1, supersedes__isnull=False),
                name="budgeting_version_revision",
            ),
            models.CheckConstraint(
                condition=models.Q(number=1) | ~models.Q(reason=""),
                name="budgeting_version_reason",
            ),
            models.CheckConstraint(
                condition=~models.Q(sod_applied=True)
                | ~models.Q(approved_by=models.F("submitted_by")),
                name="budgeting_version_sod",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["DRAFT"])
                | (~models.Q(content_hash="") & models.Q(submitted_at__isnull=False)),
                name="budgeting_version_submitted",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["DRAFT", "SUBMITTED"])
                | models.Q(approved_at__isnull=False, sod_applied__isnull=False),
                name="budgeting_version_approved",
            ),
        ]


class BudgetLine(TenantOwned):
    class Method(models.TextChoices):
        MANUAL = "MANUAL"
        EVEN = "EVEN"
        SEASONAL = "SEASONAL"
        PROFILE = "PROFILE"
        DRIVER = "DRIVER"

    version = models.ForeignKey(BudgetVersion, on_delete=models.CASCADE, related_name="lines")
    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    seq = models.PositiveIntegerField()
    taxonomy_line = models.ForeignKey(
        "metrics.TaxonomyLine", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    account_id = models.UUIDField(null=True, blank=True)  # ledger_account, same entity
    dimension_value_id = models.UUIDField(null=True, blank=True)  # ledger_dimension_value
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.MANUAL)
    method_params = models.JSONField(default=dict, blank=True)
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "budgeting_line"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(taxonomy_line__isnull=True, account_id__isnull=False)
                | models.Q(taxonomy_line__isnull=False, account_id__isnull=True),
                name="budgeting_line_subject",
            ),
            models.UniqueConstraint(
                fields=["version", "taxonomy_line", "account_id", "dimension_value_id"],
                name="budgeting_line_unique",
                nulls_distinct=False,
            ),
            models.UniqueConstraint(fields=["version", "seq"], name="budgeting_line_seq"),
        ]


class BudgetAmount(TenantOwned):
    line = models.ForeignKey(BudgetLine, on_delete=models.CASCADE, related_name="amounts")
    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    month = models.DateField()  # first day of the month
    amount = models.DecimalField(max_digits=19, decimal_places=2)
    nature = models.CharField(max_length=6, default="BUDGET")

    class Meta:
        db_table = "budgeting_amount"
        constraints = [
            models.UniqueConstraint(fields=["line", "month"], name="budgeting_amount_month"),
            models.CheckConstraint(
                condition=models.Q(nature="BUDGET"), name="budgeting_amount_nature"
            ),
        ]


class BudgetEvent(TenantOwned):
    class Action(models.TextChoices):
        CREATED = "CREATED"
        LINES_SAVED = "LINES_SAVED"
        SUBMITTED = "SUBMITTED"
        RETURNED = "RETURNED"
        APPROVED = "APPROVED"
        LOCKED = "LOCKED"
        SUPERSEDED = "SUPERSEDED"
        REVISION_STARTED = "REVISION_STARTED"

    version = models.ForeignKey(BudgetVersion, on_delete=models.CASCADE, related_name="events")
    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    seq = models.PositiveIntegerField()
    action = models.CharField(max_length=20, choices=Action.choices)
    actor = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    comment = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "budgeting_event"
        constraints = [
            models.UniqueConstraint(fields=["version", "seq"], name="budgeting_event_seq"),
        ]


class BudgetOwner(TenantOwned):
    """A department's (or project's) budget owner: a user who may see and edit that dimension
    value's lines in this budget's drafts, even without ``budget.read`` (AC-BU6)."""

    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name="owners")
    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    dimension_value_id = models.UUIDField()
    user = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "budgeting_owner"
        constraints = [
            models.UniqueConstraint(
                fields=["budget", "dimension_value_id", "user"], name="budgeting_owner_unique"
            ),
        ]


class VarianceExplanation(TenantOwned):
    """Why a budget line's variance happened, for one period view (M4-3, AC-BU5). Append-only:
    a change adds a row, and the latest row is the current explanation."""

    class View(models.TextChoices):
        MONTH = "MONTH"
        QTD = "QTD"
        YTD = "YTD"
        FULL_YEAR = "FULL_YEAR"

    version = models.ForeignKey(BudgetVersion, on_delete=models.PROTECT, related_name="+")
    line = models.ForeignKey(BudgetLine, on_delete=models.PROTECT, related_name="+")
    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    month = models.DateField()
    view = models.CharField(max_length=10, choices=View.choices)
    comparison = models.CharField(max_length=24)
    comment = models.CharField(max_length=1000)
    seq = models.PositiveIntegerField()
    author = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "budgeting_explanation"
        constraints = [
            models.UniqueConstraint(
                fields=["line", "month", "view", "comparison", "seq"],
                name="budgeting_explanation_seq",
            ),
            models.CheckConstraint(
                condition=~models.Q(comment=""), name="budgeting_explanation_comment"
            ),
        ]


class PeriodReview(TenantOwned):
    """A month's budget review marked complete: every variance above the thresholds was
    explained at that moment (AC-BU5). Append-only."""

    version = models.ForeignKey(BudgetVersion, on_delete=models.PROTECT, related_name="+")
    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    month = models.DateField()
    actuals_watermark = models.BigIntegerField()
    completed_by = models.ForeignKey(USER, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "budgeting_review"
        constraints = [
            models.UniqueConstraint(fields=["version", "month"], name="budgeting_review_month"),
        ]
