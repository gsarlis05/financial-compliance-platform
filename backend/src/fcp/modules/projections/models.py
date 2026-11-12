"""Assumption sets (M6-2): the drivers of a projection, by month.

- A set belongs to a legal entity and a family (its versions). It starts as a ``DRAFT``; once
  ``APPROVED`` it never changes, and approving a later version of the family marks the earlier
  approved one ``SUPERSEDED`` (database triggers, doc 10 P5).
- Values can be added or changed only while their set is a draft (database trigger). Each value
  says where it came from: last year's actuals, the approved budget, a default, or a person.
"""

import uuid

from django.conf import settings
from django.db import models

from fcp.core.db.models import TenantOwned

LEGAL_ENTITY = "tenancy.LegalEntity"


class AssumptionSet(TenantOwned):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        APPROVED = "APPROVED"
        SUPERSEDED = "SUPERSEDED"

    class StartFrom(models.TextChoices):
        ACTUALS = "ACTUALS"
        BUDGET = "BUDGET"
        EMPTY = "EMPTY"

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    family_id = models.UUIDField(default=uuid.uuid4)
    version = models.PositiveIntegerField(default=1)
    name = models.CharField(max_length=120)
    cutover = models.DateField()  # last day of the last actual month
    months = models.PositiveSmallIntegerField()  # horizon: 12, 24 or 36
    start_from = models.CharField(max_length=8, choices=StartFrom.choices)
    note = models.CharField(max_length=500, blank=True)  # how it was started
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    supersedes = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "projections_assumption_set"
        constraints = [
            models.UniqueConstraint(
                fields=["family_id", "version"], name="projections_set_version_once"
            ),
            models.CheckConstraint(
                condition=models.Q(months__in=[12, 24, 36]), name="projections_set_months"
            ),
            models.CheckConstraint(
                condition=models.Q(status="DRAFT")
                | models.Q(approved_by__isnull=False, approved_at__isnull=False),
                name="projections_set_approved",
            ),
        ]


class AssumptionValue(TenantOwned):
    class Source(models.TextChoices):
        ACTUALS = "ACTUALS"
        BUDGET = "BUDGET"
        DEFAULT = "DEFAULT"
        MANUAL = "MANUAL"

    assumption_set = models.ForeignKey(
        AssumptionSet, on_delete=models.PROTECT, related_name="values"
    )
    driver = models.CharField(max_length=20)
    line = models.CharField(max_length=40, blank=True)  # taxonomy line, or "" for a single row
    month = models.DateField()  # first day of the month
    value = models.DecimalField(max_digits=28, decimal_places=10)
    source = models.CharField(max_length=8, choices=Source.choices)

    class Meta:
        db_table = "projections_assumption_value"
        constraints = [
            models.UniqueConstraint(
                fields=["assumption_set", "driver", "line", "month"],
                name="projections_value_once",
            )
        ]


class RollingForecast(TenantOwned):
    """A legal entity's rolling forecast setting (M6-4): the next 12 or 24 months, projected from
    the approved version of an assumption-set family, re-run as the books move. Runs are kept as
    calculation runs; this row only says what to run and who set it up."""

    legal_entity = models.OneToOneField(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    family_id = models.UUIDField()  # the approved version of this family is used
    horizon = models.PositiveSmallIntegerField()  # 12 or 24 months
    active = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )  # the scheduled re-run acts with this user's current permissions
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "projections_rolling_forecast"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(horizon__in=[12, 24]), name="projections_rolling_horizon"
            )
        ]
