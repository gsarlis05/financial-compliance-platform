"""Forecast settings and manual cash items (M3-7).

- ``ForecastSettings``: per legal entity, the minimum cash to keep, when an unreconciled bank
  account triggers a warning, and how supplier invoices are scheduled for payment.
- ``ManualCashItem``: a cash flow the books do not know yet (e.g. an expected grant), entered
  with a reason. It is always EXPECTED (doc 10 §3.2).

Runs pin these by copying them into their inputs, so editing them later never changes a run.
"""

from django.conf import settings
from django.db import models

from fcp.core.db.models import TenantOwned

LEGAL_ENTITY = "tenancy.LegalEntity"


class ForecastSettings(TenantOwned):
    class PayablesPolicy(models.TextChoices):
        DUE_DATE = "DUE_DATE"  # pay on the due date
        WEEKDAY = "WEEKDAY"  # pay on a fixed weekday, the last one on or before the due date

    legal_entity = models.OneToOneField(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    minimum_cash = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    unreconciled_warning_days = models.PositiveSmallIntegerField(default=7)
    payables_policy = models.CharField(
        max_length=10, choices=PayablesPolicy.choices, default=PayablesPolicy.DUE_DATE
    )
    payables_weekday = models.PositiveSmallIntegerField(default=4, help_text="0 Monday … 6 Sunday")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cashflow_settings"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(minimum_cash__gte=0), name="cashflow_settings_minimum"
            ),
            models.CheckConstraint(
                condition=models.Q(payables_weekday__lte=6), name="cashflow_settings_weekday"
            ),
        ]


class ManualCashItem(TenantOwned):
    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    day = models.DateField()
    amount = models.DecimalField(max_digits=19, decimal_places=2, help_text="Receipts positive")
    category = models.CharField(max_length=20)
    reason = models.CharField(max_length=300)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "cashflow_manual_item"
        constraints = [
            models.CheckConstraint(condition=~models.Q(amount=0), name="cashflow_manual_nonzero"),
        ]
        indexes = [models.Index(fields=["legal_entity", "day"])]
