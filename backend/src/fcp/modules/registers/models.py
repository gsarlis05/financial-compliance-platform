"""Registers: customers and suppliers (counterparties) and payment allocations (backlog M2-2).

Open items are not a separate copy of the books: they are the posted journal lines on control
accounts (trade receivables and payables), each tagged with a counterparty. A debit line on a
receivables account is an invoice; a credit line is a payment or credit note. ``Allocation``
matches one against the other. Therefore the open items of a control account always add up to
its ledger balance (AC-M2-2), by construction.
"""

from django.conf import settings
from django.db import models

from fcp.core.db.models import TenantOwned

LEGAL_ENTITY = "tenancy.LegalEntity"


class Counterparty(TenantOwned):
    class Kind(models.TextChoices):
        CUSTOMER = "CUSTOMER"
        SUPPLIER = "SUPPLIER"
        BOTH = "BOTH"
        EMPLOYEE = "EMPLOYEE"
        TAX_AUTHORITY = "TAX_AUTHORITY"
        LENDER = "LENDER"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        INACTIVE = "INACTIVE"

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    code = models.CharField(max_length=30)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    # Personal data (GDPR): never logged; masked in audit events (doc 04, doc 07).
    name = models.CharField(max_length=200)
    vat_no = models.CharField(max_length=30, blank=True)
    email = models.EmailField(max_length=320, blank=True)
    payment_terms_days = models.PositiveSmallIntegerField(default=30)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "registers_counterparty"
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "code"], name="registers_counterparty_code_unique"
            ),
        ]


class Allocation(TenantOwned):
    """Part (or all) of a credit line on a control account settles part of a debit line.

    On receivables the debit line is the invoice and the credit line the payment or credit note;
    on payables it is the other way round. The database enforces (migration 0003): both lines
    posted, same control account and counterparty, positive amount, and never more allocated than
    a line's amount. ``allocated_on`` is the later of the two accounting dates, so ageing at any
    date is reproducible.
    """

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    debit_line = models.ForeignKey("ledger.JournalLine", on_delete=models.PROTECT, related_name="+")
    credit_line = models.ForeignKey(
        "ledger.JournalLine", on_delete=models.PROTECT, related_name="+"
    )
    amount = models.DecimalField(max_digits=19, decimal_places=4)
    allocated_on = models.DateField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "registers_allocation"
        constraints = [
            models.UniqueConstraint(
                fields=["debit_line", "credit_line"], name="registers_allocation_pair_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="registers_allocation_positive"
            ),
        ]
        indexes = [models.Index(fields=["credit_line"])]


class OpenItemFlag(TenantOwned):
    """Workflow state of one open item (a control-account line): disputed, with a note."""

    line = models.OneToOneField("ledger.JournalLine", on_delete=models.PROTECT, related_name="+")
    disputed = models.BooleanField(default=False)
    note = models.CharField(max_length=500, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "registers_open_item_flag"


# --- commitments: recurring obligations, loans and holidays (M3-4) -------------------------------
#
# Obligations and loans are versioned: a change supersedes the current version and adds a new one
# with the same ``series_id`` (a forecast run pins the exact versions it used, doc 10 P4/P5).
# Retiring one supersedes it without a successor. Versions are never deleted or edited (trigger).


class Versioned(TenantOwned):
    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    series_id = models.UUIDField()
    version = models.PositiveIntegerField()
    superseded_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        abstract = True


class RecurringObligation(Versioned):
    class Category(models.TextChoices):
        RENT = "RENT"
        PAYROLL = "PAYROLL"
        SOCIAL_INSURANCE = "SOCIAL_INSURANCE"
        SUBSCRIPTION = "SUBSCRIPTION"
        LEASE = "LEASE"
        INSURANCE = "INSURANCE"
        UTILITIES = "UTILITIES"
        INCOME = "INCOME"
        OTHER = "OTHER"

    class Direction(models.TextChoices):
        OUTFLOW = "OUTFLOW"
        INFLOW = "INFLOW"

    name = models.CharField(max_length=120)
    category = models.CharField(max_length=20, choices=Category.choices)
    direction = models.CharField(max_length=8, choices=Direction.choices)
    amount = models.DecimalField(max_digits=19, decimal_places=2)
    currency = models.CharField(max_length=3, default="EUR")
    frequency = models.CharField(max_length=10)  # schedules.Frequency
    interval = models.PositiveSmallIntegerField(default=1)
    day_of_month = models.PositiveSmallIntegerField(null=True, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    adjust = models.CharField(max_length=20, default="NONE")  # calendar.Adjust
    contractual = models.BooleanField(help_text="COMMITTED if contractual, else EXPECTED")
    counterparty = models.ForeignKey(
        Counterparty, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "registers_recurring_obligation"
        constraints = [
            models.UniqueConstraint(fields=["series_id", "version"], name="registers_obl_version"),
            models.UniqueConstraint(
                fields=["series_id"], condition=models.Q(superseded_at__isnull=True),
                name="registers_obl_one_current",
            ),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="registers_obl_amount"),
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="registers_obl_dates",
            ),
        ]  # fmt: skip
        indexes = [models.Index(fields=["legal_entity", "superseded_at"])]


class DebtInstrument(Versioned):
    class Kind(models.TextChoices):
        TERM_LOAN = "TERM_LOAN"
        LEASE = "LEASE"
        DIRECTOR_LOAN = "DIRECTOR_LOAN"
        OVERDRAFT = "OVERDRAFT"  # a facility: limit only, no schedule
        REVOLVER = "REVOLVER"  # a facility: limit only, no schedule

    class RateType(models.TextChoices):
        FIXED = "FIXED"
        VARIABLE = "VARIABLE"

    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    lender = models.ForeignKey(
        Counterparty, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    currency = models.CharField(max_length=3, default="EUR")
    principal = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    facility_limit = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    start_date = models.DateField()
    maturity_date = models.DateField(null=True, blank=True)
    payment_frequency_months = models.PositiveSmallIntegerField(default=1)
    rate_type = models.CharField(max_length=8, choices=RateType.choices)
    fixed_rate = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    reference_rate_key = models.CharField(max_length=40, blank=True)
    margin = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    assumed_reference_rate = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text="Until scenarios supply it (M5): the reference rate assumed for the schedule",
    )  # fmt: skip
    day_count = models.CharField(max_length=8)  # schedules.DayCount
    repayment_type = models.CharField(max_length=16, blank=True)  # schedules.Repayment
    interest_only_periods = models.PositiveSmallIntegerField(default=0)
    adjust = models.CharField(max_length=20, default="MODIFIED_FOLLOWING")
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "registers_debt_instrument"
        constraints = [
            models.UniqueConstraint(fields=["series_id", "version"], name="registers_debt_version"),
            models.UniqueConstraint(
                fields=["series_id"], condition=models.Q(superseded_at__isnull=True),
                name="registers_debt_one_current",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=["OVERDRAFT", "REVOLVER"], facility_limit__gt=0,
                                   principal__isnull=True)
                | (~models.Q(kind__in=["OVERDRAFT", "REVOLVER"])
                   & models.Q(principal__gt=0, maturity_date__isnull=False)),
                name="registers_debt_shape",
            ),
            models.CheckConstraint(
                condition=models.Q(rate_type="FIXED", fixed_rate__isnull=False)
                | models.Q(rate_type="VARIABLE", margin__isnull=False,
                           assumed_reference_rate__isnull=False),
                name="registers_debt_rate",
            ),
        ]  # fmt: skip
        indexes = [models.Index(fields=["legal_entity", "superseded_at"])]


class EntityHoliday(TenantOwned):
    """Non-business days of an entity, as data (no public holidays are built in: none are
    verified). Used to move payment dates to business days."""

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    day = models.DateField()
    name = models.CharField(max_length=100)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "registers_entity_holiday"
        constraints = [
            models.UniqueConstraint(fields=["legal_entity", "day"], name="registers_holiday_once"),
        ]


class TaxPayment(Versioned):
    """A tax payment entered by hand (M3-5): no due dates are built in until a tax professional
    has verified them (decision #93). COMMITTED when assessed or returned, EXPECTED when
    estimated. A paid one is no longer a forecast flow (the bank shows the actual payment)."""

    class Kind(models.TextChoices):
        VAT = "VAT"
        CORPORATE_TAX = "CORPORATE_TAX"  # provisional or final instalments
        SPECIAL_DEFENCE = "SPECIAL_DEFENCE"
        SOCIAL_INSURANCE = "SOCIAL_INSURANCE"
        PAYE = "PAYE"
        OTHER = "OTHER"

    class Nature(models.TextChoices):
        COMMITTED = "COMMITTED"
        EXPECTED = "EXPECTED"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    period_label = models.CharField(max_length=40, help_text="e.g. 2026-Q3 or 2026 instalment 1")
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=19, decimal_places=2)
    nature = models.CharField(max_length=10, choices=Nature.choices)
    reference = models.CharField(max_length=100, blank=True)
    paid_on = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "registers_tax_payment"
        constraints = [
            models.UniqueConstraint(fields=["series_id", "version"], name="registers_tax_version"),
            models.UniqueConstraint(
                fields=["series_id"], condition=models.Q(superseded_at__isnull=True),
                name="registers_tax_one_current",
            ),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="registers_tax_amount"),
            models.CheckConstraint(
                condition=models.Q(nature__in=["COMMITTED", "EXPECTED"]),
                name="registers_tax_nature",
            ),
        ]  # fmt: skip
        indexes = [models.Index(fields=["legal_entity", "superseded_at", "due_date"])]
