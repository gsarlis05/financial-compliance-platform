"""VAT periods and VAT period reports (version 1, V1-2, #208; ADR-0056).

- ``VatPeriodScheme``: how an entity's VAT periods run: their length in months and the month one
  of them starts, from a date on. A company's periods can change, so a scheme is never edited: a
  new one takes effect from the first day of a period, and earlier periods keep the scheme they
  had.
- ``VatReport``: the report of one VAT period, computed from the posted ledger and frozen in a
  snapshot. ``DRAFT → SIGNED_OFF → FILED``; a signed-off or filed report becomes ``SUPERSEDED``
  when a newer version of it is signed off. The person who signs off is not the preparer, except
  in a one-person workspace (V1-1). The platform never files a return: "filed" records that the
  owner filed it on the Tax Department's portal, with the portal's reference. Nothing is deleted
  and a signed-off report never changes (database triggers).
"""

from django.conf import settings
from django.db import models

from fcp.core.db.models import TenantOwned

LEGAL_ENTITY = "tenancy.LegalEntity"


class VatPeriodScheme(TenantOwned):
    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    months = models.PositiveSmallIntegerField()  # 1, 2, 3, 4, 6 or 12
    effective_from = models.DateField()  # the first day of the first period under this scheme
    note = models.CharField(max_length=500, blank=True)  # e.g. the Tax Department's letter
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "tax_vat_period_scheme"
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "effective_from"], name="tax_vat_scheme_one_per_date"
            ),
            models.CheckConstraint(
                condition=models.Q(months__in=[1, 2, 3, 4, 6, 12]), name="tax_vat_scheme_months"
            ),
        ]


class VatReport(TenantOwned):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        SIGNED_OFF = "SIGNED_OFF"
        FILED = "FILED"
        SUPERSEDED = "SUPERSEDED"

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    period_start = models.DateField()
    period_end = models.DateField()
    version = models.PositiveSmallIntegerField(default=1)
    supersedes = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    snapshot = models.JSONField(default=dict)  # every figure and line, frozen when generated
    snapshot_hash = models.CharField(max_length=64)
    watermark = models.BigIntegerField()  # the entity's last posting when generated
    generated_at = models.DateTimeField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    due_date = models.DateField(null=True, blank=True)  # entered by the owner
    signed_off_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    signed_off_at = models.DateTimeField(null=True, blank=True)
    self_approved = models.BooleanField(default=False)  # signed off by its preparer (V1-1)
    filed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    filed_on = models.DateField(null=True, blank=True)  # the date the owner filed it
    filing_reference = models.CharField(max_length=100, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)
    settlement_entry_id = models.UUIDField(null=True, blank=True)  # the prepared VAT settlement

    class Meta:
        db_table = "tax_vat_report"
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "period_start", "version"], name="tax_vat_report_version"
            ),
            # At most one report per period that is not superseded and not a draft beside it.
            models.UniqueConstraint(
                fields=["legal_entity", "period_start"],
                condition=models.Q(status="DRAFT"),
                name="tax_vat_report_one_draft",
            ),
            models.CheckConstraint(
                condition=models.Q(period_end__gte=models.F("period_start")),
                name="tax_vat_report_period",
            ),
            models.CheckConstraint(
                condition=models.Q(status="DRAFT")
                | models.Q(signed_off_by__isnull=False, signed_off_at__isnull=False),
                name="tax_vat_report_signed",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="FILED")
                | (models.Q(filed_on__isnull=False) & ~models.Q(filing_reference="")),
                name="tax_vat_report_filed",
            ),
            models.CheckConstraint(
                condition=models.Q(signed_off_by__isnull=True)
                | ~models.Q(signed_off_by=models.F("created_by"))
                | models.Q(self_approved=True),
                name="tax_vat_report_sod",
            ),
            models.CheckConstraint(
                condition=models.Q(self_approved=False)
                | models.Q(signed_off_by=models.F("created_by")),
                name="tax_vat_report_self_approved",
            ),
        ]
