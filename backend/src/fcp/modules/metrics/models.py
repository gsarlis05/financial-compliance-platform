"""Shared calculation framework, part 1: financial taxonomy and account mapping (M2-6, ADR-0009).

The taxonomy is versioned reference data (global, read-only for the runtime role). Each entity maps
its ledger accounts to taxonomy lines; the same mapping drives statements (M2-8), KPIs, budgets and
projections. Mappings are never overwritten: a change supersedes the current row and adds a new
one, so the full history is kept (``superseded_at``). Accounts are referenced by key only
(``account_id``), as the planning domain never imports the ledger (ADR-0007); a composite foreign
key in the database still guarantees the account exists in the same tenant.
"""

from django.conf import settings
from django.db import models

from fcp.core.db.models import TenantOwned


class TaxonomyVersion(models.Model):
    id = models.CharField(primary_key=True, max_length=40)  # e.g. "IFRS_SME_CY@1.0"
    key = models.CharField(max_length=30)
    semver = models.CharField(max_length=10)
    name = models.CharField(max_length=200)
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "metrics_taxonomy_version"


class TaxonomyLine(models.Model):
    class Statement(models.TextChoices):
        BALANCE_SHEET = "BS"
        PROFIT_AND_LOSS = "PL"

    id = models.CharField(primary_key=True, max_length=80)  # "<version>:<code>"
    version = models.ForeignKey(TaxonomyVersion, on_delete=models.PROTECT, related_name="lines")
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=200)
    name_el = models.CharField(max_length=200, blank=True)
    statement = models.CharField(max_length=2, choices=Statement.choices)
    section = models.CharField(max_length=40)
    account_types = models.CharField(max_length=60, help_text="Comma-separated account types")
    direction = models.CharField(max_length=14)  # HIGHER_BETTER | LOWER_BETTER
    order = models.PositiveIntegerField()

    class Meta:
        db_table = "metrics_taxonomy_line"
        constraints = [
            models.UniqueConstraint(fields=["version", "code"], name="metrics_line_code_unique"),
        ]

    def accepts(self, account_type: str) -> bool:
        return account_type in self.account_types.split(",")


class AccountTaxonomyMap(TenantOwned):
    legal_entity = models.ForeignKey(
        "tenancy.LegalEntity", on_delete=models.PROTECT, related_name="+"
    )
    account_id = models.UUIDField()
    taxonomy_version = models.ForeignKey(
        TaxonomyVersion, on_delete=models.PROTECT, related_name="+"
    )
    line = models.ForeignKey(TaxonomyLine, on_delete=models.PROTECT, related_name="+")
    superseded_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "metrics_account_taxonomy_map"
        constraints = [
            # At most one current mapping per account and taxonomy version.
            models.UniqueConstraint(
                fields=["account_id", "taxonomy_version"],
                condition=models.Q(superseded_at__isnull=True),
                name="metrics_map_one_current",
            ),
        ]
        indexes = [models.Index(fields=["legal_entity", "taxonomy_version"])]
