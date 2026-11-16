"""Scenarios (M7-1, doc 10 §8, doc 03 ``SCENARIO`` and ``SCENARIO_OVERRIDE``).

- A scenario belongs to a legal entity and pins an approved assumption set as its base. Its
  figures are always ``HYPOTHETICAL``; it never changes its base or anything else.
- Lifecycle ``DRAFT → SHARED → ARCHIVED`` (or ``DRAFT → ARCHIVED``). A draft is visible only to
  its author; a shared scenario is visible to everyone who can read plans of the entity and never
  changes (copy it to change it). Nothing is deleted (database triggers).
- Overrides are an ordered list of typed objects (``overrides.py``), changed only while the
  scenario is a draft (database trigger).
"""

from django.conf import settings
from django.db import models

from fcp.core.db.models import TenantOwned

from .overrides import TYPES


class Scenario(TenantOwned):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        SHARED = "SHARED"
        ARCHIVED = "ARCHIVED"

    legal_entity = models.ForeignKey("tenancy.LegalEntity", on_delete=models.PROTECT,
                                     related_name="+")  # fmt: skip
    base_set = models.ForeignKey("projections.AssumptionSet", on_delete=models.PROTECT,
                                 related_name="+")  # fmt: skip
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=1000, blank=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.DRAFT)
    copied_from = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")  # fmt: skip
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name="+")  # fmt: skip
    shared_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "scenarios_scenario"
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(status="SHARED") | models.Q(shared_at__isnull=False),
                name="scenarios_shared_at",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="ARCHIVED") | models.Q(archived_at__isnull=False),
                name="scenarios_archived_at",
            ),
        ]
        indexes = [models.Index(fields=["legal_entity", "status", "created_at"])]


class ScenarioOverride(TenantOwned):
    scenario = models.ForeignKey(Scenario, on_delete=models.PROTECT, related_name="overrides")
    seq = models.PositiveSmallIntegerField()  # the order in which overrides apply
    type = models.CharField(max_length=12, choices=[(t, t) for t in TYPES])
    params = models.JSONField()  # validated and normalised per type (overrides.clean)
    rationale = models.CharField(max_length=1000, blank=True)

    class Meta:
        db_table = "scenarios_override"
        constraints = [
            models.UniqueConstraint(
                fields=["scenario", "seq"],
                name="scenarios_override_seq",
                deferrable=models.Deferrable.DEFERRED,
            ),
        ]
