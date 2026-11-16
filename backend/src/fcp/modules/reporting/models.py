"""``reporting.actuals`` read model (M2-7, ADR-0007): the only path through which planning and CFO
modules read historical figures.

Facts are derived from posted journal lines and are rebuildable at any time:
- ``FactMonthly``: debit and credit totals per account and calendar month (accounting date);
- ``FactDaily``: the same per day (cash views select the cash accounts, e.g. mapped to BS.CASH);
- ``ActualsState``: per tenant, the highest ``posting_seq`` already included (the watermark).

Every calculation that reads actuals records the watermark it used, so results are reproducible.
Accounts are referenced by key; composite database keys keep them inside the tenant and entity.
"""

from django.db import models

from fcp.core.db.models import TenantOwned


class FactMonthly(TenantOwned):
    legal_entity = models.ForeignKey("tenancy.LegalEntity", on_delete=models.PROTECT,
                                     related_name="+")  # fmt: skip
    account_id = models.UUIDField()
    month = models.DateField(help_text="First day of the month")
    debit_total = models.DecimalField(max_digits=19, decimal_places=4)
    credit_total = models.DecimalField(max_digits=19, decimal_places=4)

    class Meta:
        db_table = "reporting_fact_monthly"
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "account_id", "month"], name="reporting_monthly_key"
            ),
        ]


class FactDaily(TenantOwned):
    legal_entity = models.ForeignKey("tenancy.LegalEntity", on_delete=models.PROTECT,
                                     related_name="+")  # fmt: skip
    account_id = models.UUIDField()
    day = models.DateField()
    debit_total = models.DecimalField(max_digits=19, decimal_places=4)
    credit_total = models.DecimalField(max_digits=19, decimal_places=4)

    class Meta:
        db_table = "reporting_fact_daily"
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "account_id", "day"], name="reporting_daily_key"
            ),
        ]


class ActualsState(TenantOwned):
    watermark = models.BigIntegerField(default=0, help_text="Highest posting_seq included")
    refreshed_at = models.DateTimeField(null=True, blank=True)
    rebuilt_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "reporting_actuals_state"
        constraints = [
            models.UniqueConstraint(fields=["tenant"], name="reporting_state_one_per_tenant"),
        ]
