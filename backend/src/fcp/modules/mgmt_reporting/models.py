"""Management report packs (M8-1, doc 10 §9, FR-M1, FR-E3).

- A pack belongs to one legal entity and one reporting period (a month, a fiscal quarter or a fiscal
  year). Generating it freezes a **snapshot**: every figure it shows, with its nature, and the
  references used (calc runs, budget versions, the ledger watermark). The snapshot is stored, so
  the pack reads the same for ever.
- Lifecycle ``DRAFT → IN_REVIEW → FINAL`` (a reviewer can return it to ``DRAFT``); a final pack
  becomes ``SUPERSEDED`` when a newer version of it is finalised. The reviewer is never the
  preparer. A final pack never changes and nothing is deleted (database triggers).
- Versions of one pack share a ``family_id``; each new version names the one it supersedes.
"""

from django.conf import settings
from django.db import models

from fcp.core.db.models import TenantOwned


class ReportPack(TenantOwned):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        IN_REVIEW = "IN_REVIEW"
        FINAL = "FINAL"
        SUPERSEDED = "SUPERSEDED"

    class PeriodKind(models.TextChoices):
        MONTH = "MONTH"
        QUARTER = "QUARTER"
        YEAR = "YEAR"

    legal_entity = models.ForeignKey("tenancy.LegalEntity", on_delete=models.PROTECT,
                                     related_name="+")  # fmt: skip
    family_id = models.UUIDField()  # every version of one pack
    version = models.PositiveSmallIntegerField(default=1)
    supersedes = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")  # fmt: skip
    title = models.CharField(max_length=160)
    period_kind = models.CharField(max_length=7, choices=PeriodKind.choices)
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    sections = models.JSONField(default=list)  # the sections shown, in order (M8-2)
    columns = models.JSONField(default=list)  # the comparison columns shown (M8-2)
    snapshot = models.JSONField(default=dict)  # every figure, frozen at generation
    snapshot_hash = models.CharField(max_length=64)
    watermark = models.BigIntegerField()  # the last posting included
    generated_at = models.DateTimeField()
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                     related_name="+")  # fmt: skip
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name="+")  # fmt: skip
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.PROTECT, related_name="+")  # fmt: skip
    review_note = models.CharField(max_length=1000, blank=True)
    finalised_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "mgmt_reporting_pack"
        constraints = [
            models.UniqueConstraint(
                fields=["family_id", "version"], name="mgmt_reporting_pack_version"
            ),
            # At most one open (draft or in review) version of a pack at a time.
            models.UniqueConstraint(
                fields=["family_id"],
                condition=models.Q(status__in=["DRAFT", "IN_REVIEW"]),
                name="mgmt_reporting_pack_one_open",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="FINAL")
                | models.Q(finalised_at__isnull=False, reviewed_by__isnull=False),
                name="mgmt_reporting_pack_final",
            ),
            models.CheckConstraint(
                condition=models.Q(period_start__lte=models.F("period_end")),
                name="mgmt_reporting_pack_period",
            ),
        ]
        indexes = [models.Index(fields=["legal_entity", "period_end", "created_at"])]


class PackComment(TenantOwned):
    """Human-written commentary on one section of a pack (M8-2, doc 10 §9). Append-only: a change
    adds a row and the latest row of a section is the current text. Written only while the pack is
    a draft, so a pack in review or final keeps its commentary (database trigger)."""

    pack = models.ForeignKey(ReportPack, on_delete=models.PROTECT, related_name="+")
    section = models.CharField(max_length=20)
    seq = models.PositiveIntegerField()
    text = models.CharField(max_length=4000, blank=True)  # empty: the comment was removed
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                               related_name="+")  # fmt: skip

    class Meta:
        db_table = "mgmt_reporting_comment"
        constraints = [
            models.UniqueConstraint(
                fields=["pack", "section", "seq"], name="mgmt_reporting_comment_seq"
            ),
        ]


class PackRisk(TenantOwned):
    """One risk in a pack's risks section (M8-2): written by people, never generated.
    Append-only like commentary: ``ref`` names the risk, the latest ``seq`` is its current
    state."""

    class RiskStatus(models.TextChoices):
        OPEN = "OPEN"
        MONITORING = "MONITORING"
        CLOSED = "CLOSED"

    pack = models.ForeignKey(ReportPack, on_delete=models.PROTECT, related_name="+")
    ref = models.PositiveSmallIntegerField()
    seq = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    owner = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=10, choices=RiskStatus.choices,
                              default=RiskStatus.OPEN)  # fmt: skip
    mitigation = models.CharField(max_length=1000, blank=True)
    removed = models.BooleanField(default=False)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                               related_name="+")  # fmt: skip

    class Meta:
        db_table = "mgmt_reporting_risk"
        constraints = [
            models.UniqueConstraint(fields=["pack", "ref", "seq"], name="mgmt_reporting_risk_seq"),
        ]
