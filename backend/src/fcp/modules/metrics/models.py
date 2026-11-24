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


# --- calculation runs (M3-2, doc 10 §2.3, ADR-0009) -----------------------------------------------

NATURES = ("ACTUAL", "COMMITTED", "EXPECTED", "HYPOTHETICAL", "BUDGET", "FORECAST", "TARGET")
# Values are stored exactly as computed (ratios are not rounded): up to 28 decimal places and 22
# integer digits (``metrics.calc`` refuses anything else rather than let the database round it).
VALUE_DIGITS, VALUE_PLACES = 50, 28


class CalcRun(TenantOwned):
    """One reproducible calculation: its inputs are pinned (ledger watermark, as-of date, versioned
    references), hashed, and the hash of its output is stored. A finished run is immutable except
    that it can become stale (newer data exists) and, if valid, be published."""

    class Status(models.TextChoices):
        RUNNING = "RUNNING"  # being written in this transaction only
        VALID = "VALID"
        INVALID = "INVALID"  # an invariant failed; cannot be published
        FAILED = "FAILED"  # the engine raised; no results

    class Trigger(models.TextChoices):
        USER = "USER"
        SYSTEM_EVENT = "SYSTEM_EVENT"
        SCHEDULE = "SCHEDULE"

    legal_entity = models.ForeignKey(
        "tenancy.LegalEntity", on_delete=models.PROTECT, related_name="+"
    )
    kind = models.CharField(max_length=30)
    engine_version = models.CharField(max_length=30)
    actuals_watermark = models.BigIntegerField()
    as_of_date = models.DateField()
    input_refs = models.JSONField(default=dict)
    input_hash = models.CharField(max_length=64)
    output_hash = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=8, choices=Status.choices)
    invariant_results = models.JSONField(default=dict)
    error = models.CharField(max_length=500, blank=True)
    stale = models.BooleanField(default=False)
    is_published = models.BooleanField(default=False)
    trigger = models.CharField(max_length=12, choices=Trigger.choices)
    supersedes = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "metrics_calc_run"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["RUNNING", "VALID", "INVALID", "FAILED"]),
                name="metrics_run_status_known",
            ),
            models.CheckConstraint(
                condition=models.Q(is_published=False) | models.Q(status="VALID"),
                name="metrics_run_published_is_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["RUNNING", "FAILED"])
                | models.Q(output_hash__regex=r"^[0-9a-f]{64}$"),
                name="metrics_run_finished_has_hash",
            ),
            models.CheckConstraint(
                condition=models.Q(input_hash__regex=r"^[0-9a-f]{64}$"),
                name="metrics_run_input_hash",
            ),
        ]
        indexes = [models.Index(fields=["legal_entity", "kind", "created_at"])]


class CalcResult(TenantOwned):
    """One value of a run, with its nature (never null) and unit. A value that is not meaningful
    (e.g. a ratio with a zero denominator) has no value and a reason instead."""

    class Granularity(models.TextChoices):
        DAY = "DAY"
        WEEK = "WEEK"
        MONTH = "MONTH"
        QUARTER = "QUARTER"
        YEAR = "YEAR"
        POINT = "POINT"  # a value at a date (a balance, a KPI at a date)

    run = models.ForeignKey(CalcRun, on_delete=models.PROTECT, related_name="results")
    seq = models.PositiveIntegerField()
    series_key = models.CharField(max_length=120)
    dimensions = models.JSONField(default=list)
    period_start = models.DateField()
    period_end = models.DateField()
    granularity = models.CharField(max_length=8, choices=Granularity.choices)
    nature = models.CharField(max_length=12)
    value = models.DecimalField(
        null=True, blank=True, max_digits=VALUE_DIGITS, decimal_places=VALUE_PLACES
    )
    unit = models.CharField(max_length=10)
    nm_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "metrics_calc_result"
        constraints = [
            models.UniqueConstraint(fields=["run", "seq"], name="metrics_result_seq_once"),
            models.CheckConstraint(
                condition=models.Q(nature__in=NATURES), name="metrics_result_nature_known"
            ),
            models.CheckConstraint(
                condition=models.Q(value__isnull=False, nm_reason="")
                | (models.Q(value__isnull=True) & ~models.Q(nm_reason="")),
                name="metrics_result_value_or_reason",
            ),
            models.CheckConstraint(
                condition=models.Q(period_end__gte=models.F("period_start")),
                name="metrics_result_period_order",
            ),
        ]
        indexes = [models.Index(fields=["run", "series_key", "period_start"])]


class CalcLineage(TenantOwned):
    """What a result was computed from: actuals (account x period), open items, schedules,
    assumptions, overrides, formulas or manual items (doc 10 P6). ``amount`` is the contribution
    when the result is a sum."""

    class InputKind(models.TextChoices):
        ACTUAL = "ACTUAL"
        ASSUMPTION = "ASSUMPTION"
        OVERRIDE = "OVERRIDE"
        OPEN_ITEM = "OPEN_ITEM"
        SCHEDULE = "SCHEDULE"
        FORMULA = "FORMULA"
        MANUAL = "MANUAL"
        RESULT = "RESULT"  # another result of the same run (e.g. a total of lines)

    result = models.ForeignKey(CalcResult, on_delete=models.PROTECT, related_name="lineage")
    seq = models.PositiveIntegerField()
    input_kind = models.CharField(max_length=12, choices=InputKind.choices)
    input_ref = models.CharField(max_length=200)
    amount = models.DecimalField(
        null=True, blank=True, max_digits=VALUE_DIGITS, decimal_places=VALUE_PLACES
    )
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "metrics_calc_lineage"
        constraints = [
            models.UniqueConstraint(fields=["result", "seq"], name="metrics_lineage_seq_once"),
        ]
