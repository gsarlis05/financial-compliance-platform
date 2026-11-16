"""Ledger: chart of accounts and fiscal calendar (docs/planning/03 §2, 05 §5).

Journal entries arrive in M1-8. Every table is tenant-owned with FORCE row-level security and
composite foreign keys that also keep rows inside one legal entity (migration 0002).
"""

from django.conf import settings
from django.db import models

from fcp.core.db.models import TenantOwned

LEGAL_ENTITY = "tenancy.LegalEntity"


class Account(TenantOwned):
    class Type(models.TextChoices):
        ASSET = "ASSET"
        LIABILITY = "LIABILITY"
        EQUITY = "EQUITY"
        INCOME = "INCOME"
        EXPENSE = "EXPENSE"

    class Side(models.TextChoices):
        DEBIT = "DEBIT"
        CREDIT = "CREDIT"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        INACTIVE = "INACTIVE"

    NORMAL_SIDE = {
        Type.ASSET: Side.DEBIT,
        Type.EXPENSE: Side.DEBIT,
        Type.LIABILITY: Side.CREDIT,
        Type.EQUITY: Side.CREDIT,
        Type.INCOME: Side.CREDIT,
    }

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=200)
    name_el = models.CharField(max_length=200, blank=True)
    type = models.CharField(max_length=16, choices=Type.choices)
    normal_side = models.CharField(max_length=6, choices=Side.choices)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    is_postable = models.BooleanField(default=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    currency = models.CharField(max_length=3, blank=True, help_text="Blank: any currency")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "ledger_account"
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "code"], name="ledger_account_code_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(code__regex=r"^[0-9A-Z][0-9A-Z.\-]{0,19}$"),
                name="ledger_account_code_format",
            ),
        ]


class FiscalYear(TenantOwned):
    class Status(models.TextChoices):
        OPEN = "OPEN"
        CLOSED = "CLOSED"

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=40)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "ledger_fiscal_year"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_date__lt=models.F("end_date")),
                name="ledger_fiscal_year_dates",
            )
        ]


class Period(TenantOwned):
    class Status(models.TextChoices):
        OPEN = "OPEN"
        SOFT_CLOSED = "SOFT_CLOSED"
        LOCKED = "LOCKED"

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.PROTECT, related_name="periods")
    number = models.PositiveSmallIntegerField()
    start_date = models.DateField()
    end_date = models.DateField()
    is_adjustment = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    status_changed_at = models.DateTimeField(null=True, blank=True)
    status_changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "ledger_period"
        constraints = [
            models.UniqueConstraint(
                fields=["fiscal_year", "number"], name="ledger_period_number_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(start_date__lte=models.F("end_date")),
                name="ledger_period_dates",
            ),
        ]
        ordering = ["fiscal_year__start_date", "number"]


# --- journal entries (backlog M1-8) --------------------------------------------------------------

# Monetary columns: NUMERIC(19,4) (doc 03 conventions; ADR-0003).


class LedgerSettings(TenantOwned):
    """Per-entity controls. The approval policy decides when a second person must approve."""

    class Approval(models.TextChoices):
        NONE = "NONE"  # preparer may post (personal finances)
        THRESHOLD = "THRESHOLD"  # approval needed above the threshold amount
        ALWAYS = "ALWAYS"

    legal_entity = models.OneToOneField(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    approval_policy = models.CharField(max_length=16, choices=Approval.choices)
    approval_threshold = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "ledger_settings"


class Journal(TenantOwned):
    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    code = models.CharField(max_length=10)
    name = models.CharField(max_length=100)

    class Meta:
        db_table = "ledger_journal"
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "code"], name="ledger_journal_code_unique"
            )
        ]


class JournalEntry(TenantOwned):
    class Status(models.TextChoices):
        DRAFT = "DRAFT"
        SUBMITTED = "SUBMITTED"
        APPROVED = "APPROVED"
        POSTED = "POSTED"
        REJECTED = "REJECTED"
        VOID = "VOID"

    class EntryType(models.TextChoices):
        STANDARD = "STANDARD"
        REVERSAL = "REVERSAL"
        ADJUSTMENT = "ADJUSTMENT"
        OPENING = "OPENING"
        CLOSING = "CLOSING"

    class Source(models.TextChoices):
        MANUAL = "MANUAL"
        IMPORT = "IMPORT"
        SYSTEM = "SYSTEM"

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    journal = models.ForeignKey(Journal, on_delete=models.PROTECT, related_name="+")
    entry_type = models.CharField(
        max_length=16, choices=EntryType.choices, default=EntryType.STANDARD
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.MANUAL)
    accounting_date = models.DateField()
    document_date = models.DateField(null=True, blank=True)
    use_adjustment_period = models.BooleanField(default=False)
    description = models.CharField(max_length=500)
    currency = models.CharField(max_length=3)
    reverses_entry = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reversed_by_entry = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    related_entry = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    correction_reason = models.CharField(max_length=500, blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_hash = models.CharField(max_length=64, blank=True)
    rejection_reason = models.CharField(max_length=500, blank=True)
    # Set at posting.
    period = models.ForeignKey(
        Period, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    fiscal_year = models.ForeignKey(
        FiscalYear, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    entry_no = models.PositiveIntegerField(null=True, blank=True)
    posting_seq = models.BigIntegerField(null=True, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_in_soft_closed = models.BooleanField(default=False)
    unlock_request_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "ledger_journal_entry"
        constraints = [
            models.UniqueConstraint(
                fields=["journal", "fiscal_year", "entry_no"], name="ledger_entry_number_unique"
            ),
            models.UniqueConstraint(
                fields=["tenant", "posting_seq"], name="ledger_entry_posting_seq_unique"
            ),
            # An entry can be reversed once: one live reversal per original (AC-C6).
            models.UniqueConstraint(
                fields=["reverses_entry"],
                condition=~models.Q(status__in=["VOID", "REJECTED"]),
                name="ledger_entry_single_reversal",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="POSTED")
                | models.Q(entry_no__isnull=False, posting_seq__isnull=False, period__isnull=False),
                name="ledger_entry_posted_fields",
            ),
        ]
        indexes = [models.Index(fields=["legal_entity", "status", "accounting_date"])]


class JournalLine(TenantOwned):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+")
    debit = models.DecimalField(max_digits=19, decimal_places=4, default=0)
    credit = models.DecimalField(max_digits=19, decimal_places=4, default=0)
    memo = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "ledger_journal_line"
        constraints = [
            models.UniqueConstraint(fields=["entry", "line_no"], name="ledger_line_number_unique"),
            # Exactly one side, strictly positive (AC-C1, enforced by the database too).
            models.CheckConstraint(
                condition=(models.Q(debit__gt=0) & models.Q(credit=0))
                | (models.Q(credit__gt=0) & models.Q(debit=0)),
                name="ledger_line_one_positive_side",
            ),
        ]


class EntrySequence(TenantOwned):
    """Gapless entry numbers per journal and fiscal year; the row is locked while posting."""

    journal = models.ForeignKey(Journal, on_delete=models.PROTECT, related_name="+")
    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.PROTECT, related_name="+")
    last_no = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "ledger_entry_sequence"
        constraints = [
            models.UniqueConstraint(
                fields=["journal", "fiscal_year"], name="ledger_sequence_unique"
            )
        ]


class PostingCounter(models.Model):
    """Per-tenant posting watermark (doc 10 §2.3); strictly increasing, gapless."""

    tenant = models.OneToOneField("tenancy.Tenant", primary_key=True, on_delete=models.PROTECT,
                                  related_name="+")  # fmt: skip
    last_seq = models.BigIntegerField(default=0)

    class Meta:
        db_table = "ledger_posting_counter"


class IdempotencyRecord(TenantOwned):
    key = models.CharField(max_length=100)
    operation = models.CharField(max_length=50)
    request_hash = models.CharField(max_length=64)
    response = models.JSONField()
    status_code = models.PositiveSmallIntegerField()

    class Meta:
        db_table = "ledger_idempotency"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "key"], name="ledger_idempotency_unique")
        ]


class AccountBalance(TenantOwned):
    """Debit and credit totals per account and period, maintained at posting (doc 05 §7).

    Rebuildable from posted lines at any time; the integrity job (M1-11) compares the two.
    """

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+")
    period = models.ForeignKey(Period, on_delete=models.PROTECT, related_name="+")
    debit_total = models.DecimalField(max_digits=19, decimal_places=4, default=0)
    credit_total = models.DecimalField(max_digits=19, decimal_places=4, default=0)

    class Meta:
        db_table = "ledger_account_balance"
        constraints = [
            models.UniqueConstraint(fields=["account", "period"], name="ledger_balance_unique")
        ]


class PeriodUnlock(TenantOwned):
    """A time-boxed exception to a period lock (doc 05 §4, AC-C7).

    Needs two approvals by distinct users with ``ledger.period.unlock_approve``, neither of them
    the requester. While ACTIVE and inside its window, entries may post into the locked period and
    are tagged with this unlock; the period itself stays LOCKED, so expiry re-locks automatically.
    """

    class Status(models.TextChoices):
        REQUESTED = "REQUESTED"
        ACTIVE = "ACTIVE"
        REJECTED = "REJECTED"
        CLOSED = "CLOSED"

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    period = models.ForeignKey(Period, on_delete=models.PROTECT, related_name="unlocks")
    reason = models.CharField(max_length=500)
    window_minutes = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REQUESTED)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    first_approver = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    second_approver = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    active_from = models.DateTimeField(null=True, blank=True)
    active_until = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "ledger_period_unlock"
        constraints = [
            # At most one open (requested or active) unlock per period.
            models.UniqueConstraint(
                fields=["period"],
                condition=models.Q(status__in=["REQUESTED", "ACTIVE"]),
                name="ledger_unlock_one_open_per_period",
            ),
            models.CheckConstraint(
                condition=models.Q(first_approver__isnull=True)
                | ~models.Q(first_approver=models.F("requested_by")),
                name="ledger_unlock_first_approver_not_requester",
            ),
            models.CheckConstraint(
                condition=models.Q(second_approver__isnull=True)
                | (
                    ~models.Q(second_approver=models.F("requested_by"))
                    & ~models.Q(second_approver=models.F("first_approver"))
                ),
                name="ledger_unlock_second_approver_distinct",
            ),
        ]


class IntegrityCheckRun(TenantOwned):
    """Result of one integrity check of a workspace (doc 05 §7, AC-C10)."""

    class Status(models.TextChoices):
        PASSED = "PASSED"
        FAILED = "FAILED"

    status = models.CharField(max_length=8, choices=Status.choices)
    results = models.JSONField()
    trigger = models.CharField(max_length=16, default="SCHEDULE")
    finished_at = models.DateTimeField()

    class Meta:
        db_table = "ledger_integrity_check_run"
        indexes = [models.Index(fields=["tenant", "-created_at"])]


# --- analytical dimensions (M2-1, docs/planning/03 §6) --------------------------------------------


class Dimension(TenantOwned):
    """An analysis axis of one legal entity, e.g. department, project or cost centre."""

    class Kind(models.TextChoices):
        DEPARTMENT = "DEPARTMENT"
        PROJECT = "PROJECT"
        COST_CENTRE = "COST_CENTRE"
        CUSTOM = "CUSTOM"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        INACTIVE = "INACTIVE"

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "ledger_dimension"
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "code"], name="ledger_dimension_code_unique"
            ),
        ]


class DimensionValue(TenantOwned):
    dimension = models.ForeignKey(Dimension, on_delete=models.PROTECT, related_name="values")
    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=200)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    status = models.CharField(
        max_length=16, choices=Dimension.Status.choices, default=Dimension.Status.ACTIVE
    )

    class Meta:
        db_table = "ledger_dimension_value"
        constraints = [
            models.UniqueConstraint(
                fields=["dimension", "code"], name="ledger_dimension_value_code_unique"
            ),
        ]


class AccountDimensionRule(TenantOwned):
    """Per account: a dimension is REQUIRED on every posted line, or BLOCKED. Default: optional."""

    class Rule(models.TextChoices):
        REQUIRED = "REQUIRED"
        BLOCKED = "BLOCKED"

    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="dimension_rules")
    dimension = models.ForeignKey(Dimension, on_delete=models.PROTECT, related_name="+")
    rule = models.CharField(max_length=8, choices=Rule.choices)

    class Meta:
        db_table = "ledger_account_dimension_rule"
        constraints = [
            models.UniqueConstraint(
                fields=["account", "dimension"], name="ledger_account_dimension_rule_unique"
            ),
        ]


class LineDimension(TenantOwned):
    """One dimension value tagged on one journal line (at most one value per dimension)."""

    line = models.ForeignKey(JournalLine, on_delete=models.CASCADE, related_name="dimension_tags")
    dimension = models.ForeignKey(Dimension, on_delete=models.PROTECT, related_name="+")
    value = models.ForeignKey(DimensionValue, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "ledger_line_dimension"
        constraints = [
            models.UniqueConstraint(
                fields=["line", "dimension"], name="ledger_line_dimension_unique"
            ),
        ]
        indexes = [models.Index(fields=["value", "line"])]
