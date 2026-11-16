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
