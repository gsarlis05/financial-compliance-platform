"""Tax rule sets as reference data (M6F-2, #147; owner decision D4).

Global, read-only for the runtime role, seeded by migrations from ``data/<jurisdiction>.json``.
A rule set applies to the tax years from ``effective_from`` to ``effective_to``; for losses, the
carry-forward period is the one of the rule set in force for the year the loss arose. ``verified``
stays False until a qualified tax professional confirms the set (owner item #154); everything
that uses an unverified set says so.
"""

from django.conf import settings
from django.db import models

from fcp.core.db.models import TenantOwned


class TaxRuleSet(models.Model):
    class Tax(models.TextChoices):
        CORPORATE_INCOME_TAX = "CORPORATE_INCOME_TAX"

    id = models.CharField(primary_key=True, max_length=40)  # e.g. "CY:CIT:2026"
    jurisdiction = models.CharField(max_length=2)
    tax = models.CharField(max_length=30, choices=Tax.choices)
    effective_from = models.DateField()  # the first day of the first tax year it applies to
    effective_to = models.DateField(null=True, blank=True)  # null: still in force
    rate = models.DecimalField(max_digits=7, decimal_places=4)  # 0.15 for 15%
    loss_carryforward_years = models.PositiveSmallIntegerField()
    tax_year_start_month = models.PositiveSmallIntegerField(default=1)
    # [{"month": 7, "day": 31, "share": "0.5"}, ...] within the tax year; shares add up to 1.
    provisional_instalments = models.JSONField(default=list)
    final_payment_year_offset = models.PositiveSmallIntegerField()  # years after the tax year
    final_payment_month = models.PositiveSmallIntegerField()
    final_payment_day = models.PositiveSmallIntegerField()
    sources = models.JSONField(default=list)  # [{"publisher", "title", "url", "note"}]
    verified = models.BooleanField(default=False)
    verification_note = models.CharField(max_length=1000, blank=True)
    verified_by = models.CharField(max_length=200, blank=True)
    verified_on = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "taxrules_rule_set"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True)
                | models.Q(effective_to__gte=models.F("effective_from")),
                name="taxrules_window_ordered",
            ),
            models.CheckConstraint(
                condition=models.Q(rate__gte=0, rate__lt=1), name="taxrules_rate_fraction"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    tax_year_start_month__gte=1,
                    tax_year_start_month__lte=12,
                    final_payment_month__gte=1,
                    final_payment_month__lte=12,
                    final_payment_day__gte=1,
                    final_payment_day__lte=31,
                ),
                name="taxrules_calendar",
            ),
            models.CheckConstraint(
                condition=models.Q(verified=False)
                | ~models.Q(verified_by="") & models.Q(verified_on__isnull=False),
                name="taxrules_verified_by_whom",
            ),
        ]


class RuleCorrection(TenantOwned):
    """A correction of a rule for one entity, entered by the owner (brief 27, T-2, #255).

    The global rules (VAT codes, the VAT return's box rules, corporate tax rule sets) stay as
    seeded; a correction is a version for the entity from ``effective_from``, with its source.
    Corrections are never changed or deleted (database trigger): a mistake is corrected by a
    later one, which may start on the same day and then supersedes it. Each kind is checked by
    the module that owns the rule; this table only keeps them.

    - VAT_CODE: ``target`` is the code (e.g. S19); ``values`` any of rate, treatment, category,
      name, name_el. Applies to lines whose tax point (else accounting date) is on or after the
      start.
    - VAT_BOX_RULE: ``target`` is "CATEGORY|LINE"; ``values`` {"status": MAPPED or EXCLUDED,
      "boxes": [...]}. Applies to VAT returns whose period starts on or after the start.
    - CORPORATE_TAX: ``target`` is CIT; ``values`` a full rule set (rate, loss years,
      instalments, final payment). Applies to tax years starting on or after the start.
    """

    class Kind(models.TextChoices):
        VAT_CODE = "VAT_CODE"
        VAT_BOX_RULE = "VAT_BOX_RULE"
        CORPORATE_TAX = "CORPORATE_TAX"

    legal_entity = models.ForeignKey("tenancy.LegalEntity", on_delete=models.PROTECT,
                                     related_name="+")  # fmt: skip
    kind = models.CharField(max_length=16, choices=Kind.choices)
    target = models.CharField(max_length=60)
    effective_from = models.DateField()
    values = models.JSONField()
    source = models.CharField(max_length=500)
    note = models.CharField(max_length=1000, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name="+")  # fmt: skip

    class Meta:
        db_table = "taxrules_correction"
        indexes = [models.Index(fields=["legal_entity", "kind", "target", "effective_from"],
                                name="taxrules_correction_lookup")]  # fmt: skip
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(source=""), name="taxrules_correction_source"
            ),
            models.CheckConstraint(
                condition=~models.Q(target=""), name="taxrules_correction_target"
            ),
        ]
