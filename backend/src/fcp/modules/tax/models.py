"""VAT periods and VAT period reports (version 1, V1-2, #208; ADR-0056).

- ``VatPeriodScheme``: how an entity's VAT periods run: their length in months and the month one
  of them starts, from a date on. A company's periods can change, so a scheme is never edited: a
  new one takes effect from the first day of a period, and earlier periods keep the scheme they
  had.
- ``VatReport``: the report of one VAT period, computed from the posted ledger and frozen in a
  snapshot. ``DRAFT → REVIEWED → FINALISED → FILED`` (V1-2d); a reviewed report can go back to
  draft; a finalised or filed report becomes ``SUPERSEDED`` when a newer version of it is
  finalised. The reviewer and the finaliser are not the preparer, except in a one-person
  workspace (V1-1). The platform never files a return: "filed" records that the owner filed it on
  the Tax Department's portal, with the portal's reference and evidence. Nothing is deleted and a
  finalised report never changes (database triggers).
- ``VatAdjustment``: a manual change to one box of a draft, with a reason and evidence, applied
  only once approved; the figures from the ledger stay as they were.
- ``VatInclusion``: which return each ledger line was reported in. A line is in at most one active
  (finalised or filed, not superseded) return.
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
        REVIEWED = "REVIEWED"
        FINALISED = "FINALISED"
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
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=500, blank=True)  # why it went back to draft
    finalised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    finalised_at = models.DateTimeField(null=True, blank=True)
    # Reviewed or finalised by its preparer, in a one-person workspace (V1-1).
    self_approved = models.BooleanField(default=False)
    filed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    filed_on = models.DateField(null=True, blank=True)  # the date the owner filed it
    filing_reference = models.CharField(max_length=100, blank=True)
    filing_evidence = models.CharField(max_length=500, blank=True)  # e.g. the acknowledgement
    superseded_at = models.DateTimeField(null=True, blank=True)
    settlement_entry_id = models.UUIDField(null=True, blank=True)  # the prepared VAT settlement

    class Meta:
        db_table = "tax_vat_report"
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "period_start", "version"], name="tax_vat_report_version"
            ),
            # At most one report per period being prepared (draft or reviewed).
            models.UniqueConstraint(
                fields=["legal_entity", "period_start"],
                condition=models.Q(status__in=["DRAFT", "REVIEWED"]),
                name="tax_vat_report_one_open",
            ),
            models.CheckConstraint(
                condition=models.Q(period_end__gte=models.F("period_start")),
                name="tax_vat_report_period",
            ),
            models.CheckConstraint(
                condition=models.Q(status="DRAFT")
                | models.Q(reviewed_by__isnull=False, reviewed_at__isnull=False),
                name="tax_vat_report_reviewed",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["DRAFT", "REVIEWED"])
                | models.Q(finalised_by__isnull=False, finalised_at__isnull=False),
                name="tax_vat_report_finalised",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="FILED")
                | (models.Q(filed_on__isnull=False) & ~models.Q(filing_reference="")),
                name="tax_vat_report_filed",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(reviewed_by__isnull=True)
                    | ~models.Q(reviewed_by=models.F("created_by"))
                    | models.Q(self_approved=True)
                )
                & (
                    models.Q(finalised_by__isnull=True)
                    | ~models.Q(finalised_by=models.F("created_by"))
                    | models.Q(self_approved=True)
                ),
                name="tax_vat_report_sod",
            ),
            models.CheckConstraint(
                condition=models.Q(self_approved=False)
                | models.Q(reviewed_by=models.F("created_by"))
                | models.Q(finalised_by=models.F("created_by")),
                name="tax_vat_report_self_approved",
            ),
        ]


BOXES = ("1", "2", "4", "6", "7", "8A", "8B", "9", "10", "11A", "11B")  # 3 and 5 are computed


class VatAdjustment(TenantOwned):
    class Status(models.TextChoices):
        PROPOSED = "PROPOSED"
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"  # rejected by an approver, or withdrawn by its author

    report = models.ForeignKey(VatReport, on_delete=models.PROTECT, related_name="adjustments")
    box = models.CharField(max_length=3)
    amount = models.DecimalField(max_digits=19, decimal_places=2)
    reason = models.CharField(max_length=500)
    evidence = models.CharField(max_length=500)  # e.g. "adviser's letter of 3 April, in Documents"
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PROPOSED)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=500, blank=True)
    self_approved = models.BooleanField(default=False)  # approved by its author (V1-1)

    class Meta:
        db_table = "tax_vat_adjustment"
        constraints = [
            models.CheckConstraint(condition=models.Q(box__in=BOXES), name="tax_vat_adj_box"),
            models.CheckConstraint(condition=~models.Q(amount=0), name="tax_vat_adj_amount"),
            models.CheckConstraint(
                condition=~models.Q(reason="") & ~models.Q(evidence=""),
                name="tax_vat_adj_reasoned",
            ),
            models.CheckConstraint(
                condition=models.Q(status="PROPOSED")
                | models.Q(decided_by__isnull=False, decided_at__isnull=False),
                name="tax_vat_adj_decided",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="APPROVED")
                | ~models.Q(decided_by=models.F("created_by"))
                | models.Q(self_approved=True),
                name="tax_vat_adj_sod",
            ),
            models.CheckConstraint(
                condition=models.Q(self_approved=False)
                | models.Q(status="APPROVED", decided_by=models.F("created_by")),
                name="tax_vat_adj_self_approved",
            ),
        ]


class VatInclusion(TenantOwned):
    report = models.ForeignKey(VatReport, on_delete=models.PROTECT, related_name="+")
    line_id = models.UUIDField()
    entry_id = models.UUIDField()
    active = models.BooleanField(default=True)  # false once its report is superseded

    class Meta:
        db_table = "tax_vat_inclusion"
        constraints = [
            models.UniqueConstraint(fields=["report", "line_id"], name="tax_vat_inclusion_once"),
            models.UniqueConstraint(
                fields=["tenant", "line_id"],
                condition=models.Q(active=True),
                name="tax_vat_inclusion_one_return",
            ),
        ]


class VatImport(TenantOwned):
    """An import of goods (V1-2f): the customs declaration behind the import VAT one posted entry
    claims. A record is never edited; a wrong one is voided (with a reason) and recorded again,
    and it cannot be voided once its entry is in a finalised return."""

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    entry_id = models.UUIDField()  # the posted entry with the import VAT (ledger)
    customs_reference = models.CharField(max_length=50)  # e.g. the declaration's MRN
    customs_date = models.DateField()
    customs_value = models.DecimalField(max_digits=19, decimal_places=2)  # the taxable value
    import_vat = models.DecimalField(max_digits=19, decimal_places=2)  # as on the declaration
    document_id = models.UUIDField()  # the evidence, attached to the entry (documents)
    document_name = models.CharField(max_length=200)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    void_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "tax_vat_import"
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "customs_reference"],
                condition=models.Q(voided_at__isnull=True),
                name="tax_vat_import_reference_once",
            ),
            models.UniqueConstraint(
                fields=["legal_entity", "entry_id"],
                condition=models.Q(voided_at__isnull=True),
                name="tax_vat_import_entry_once",
            ),
            models.CheckConstraint(
                condition=models.Q(customs_value__gt=0, import_vat__gt=0),
                name="tax_vat_import_amounts",
            ),
            models.CheckConstraint(
                condition=~models.Q(customs_reference=""), name="tax_vat_import_reference"
            ),
            models.CheckConstraint(
                condition=models.Q(voided_at__isnull=True)
                | (models.Q(voided_by__isnull=False) & ~models.Q(void_reason="")),
                name="tax_vat_import_voided",
            ),
        ]


class VatViesStatement(TenantOwned):
    """A recapitulative (VIES) statement for one month, as the owner filed it (V1-2g). The
    platform never submits it. A correction filed later is a statement of kind CORRECTION for
    the same month. A statement is never edited; a wrong one is voided with a reason."""

    class Kind(models.TextChoices):
        ORIGINAL = "ORIGINAL"
        CORRECTION = "CORRECTION"

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    month = models.DateField()  # the first day of the month it reports
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.ORIGINAL)
    filed_on = models.DateField()
    reference = models.CharField(max_length=100)  # the submission's reference
    note = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    void_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "tax_vat_vies_statement"
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "month"],
                condition=models.Q(voided_at__isnull=True, kind="ORIGINAL"),
                name="tax_vies_one_original",
            ),
            models.CheckConstraint(condition=models.Q(month__day=1), name="tax_vies_month_start"),
            models.CheckConstraint(condition=~models.Q(reference=""), name="tax_vies_reference"),
            models.CheckConstraint(
                condition=models.Q(voided_at__isnull=True)
                | (models.Q(voided_by__isnull=False) & ~models.Q(void_reason="")),
                name="tax_vies_voided",
            ),
        ]


class VatViesLine(TenantOwned):
    """One partner on a VIES statement: its country and VAT number and the values reported."""

    statement = models.ForeignKey(VatViesStatement, on_delete=models.PROTECT, related_name="lines")
    country = models.CharField(max_length=2)
    vat_no = models.CharField(max_length=30)
    goods = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    services = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    triangular = models.DecimalField(max_digits=19, decimal_places=2, default=0)

    class Meta:
        db_table = "tax_vat_vies_line"
        constraints = [
            models.UniqueConstraint(
                fields=["statement", "country", "vat_no"], name="tax_vies_line_once"
            ),
            models.CheckConstraint(
                condition=models.Q(country__regex=r"^[A-Z]{2}$") & ~models.Q(vat_no=""),
                name="tax_vies_line_party",
            ),
            models.CheckConstraint(
                condition=~models.Q(goods=0, services=0, triangular=0),
                name="tax_vies_line_amount",
            ),
        ]
