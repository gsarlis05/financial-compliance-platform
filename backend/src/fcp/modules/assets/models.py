"""Fixed-asset register (M6-1).

- An asset's terms can be corrected only until depreciation has been prepared for it; after that
  they are locked (database trigger), and only the disposal can be recorded, once.
- A depreciation run is one month of one entity, with the draft journal entry it prepared and the
  amount per asset. Runs are never changed or deleted; a run whose entry was voided or rejected is
  cancelled and the month can be prepared again.
"""

from django.conf import settings
from django.db import models

from fcp.core.db.models import TenantOwned

LEGAL_ENTITY = "tenancy.LegalEntity"


class FixedAsset(TenantOwned):
    class Category(models.TextChoices):
        BUILDINGS = "BUILDINGS"
        MACHINERY = "MACHINERY"
        VEHICLES = "VEHICLES"
        IT_EQUIPMENT = "IT_EQUIPMENT"
        FURNITURE = "FURNITURE"
        OTHER = "OTHER"

    class Method(models.TextChoices):
        STRAIGHT_LINE = "STRAIGHT_LINE"
        DECLINING_BALANCE = "DECLINING_BALANCE"

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=16, choices=Category.choices)
    asset_account_id = models.UUIDField()  # cost
    accumulated_account_id = models.UUIDField()  # accumulated depreciation
    expense_account_id = models.UUIDField()  # depreciation expense
    acquired_on = models.DateField()
    cost = models.DecimalField(max_digits=19, decimal_places=2)
    residual_value = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    useful_life_months = models.PositiveIntegerField()
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.STRAIGHT_LINE)
    annual_rate = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    disposed_on = models.DateField(null=True, blank=True)
    disposal_proceeds = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)  # first depreciation prepared
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "assets_fixed_asset"
        constraints = [
            models.UniqueConstraint(fields=["legal_entity", "code"], name="assets_code_once"),
            models.CheckConstraint(
                condition=models.Q(
                    cost__gte=0, residual_value__gte=0, residual_value__lte=models.F("cost")
                ),
                name="assets_cost_residual",
            ),
            models.CheckConstraint(
                condition=models.Q(useful_life_months__gte=1, useful_life_months__lte=1200),
                name="assets_life",
            ),
            models.CheckConstraint(
                condition=~models.Q(method="DECLINING_BALANCE")
                | models.Q(annual_rate__gt=0, annual_rate__lte=2),
                name="assets_declining_rate",
            ),
            models.CheckConstraint(
                condition=models.Q(disposed_on__isnull=True)
                | models.Q(disposed_on__gte=models.F("acquired_on")),
                name="assets_disposed_after_acquired",
            ),
        ]


class DepreciationRun(TenantOwned):
    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    month = models.DateField()  # first day of the month
    entry_id = models.UUIDField()  # the draft journal entry it prepared
    total = models.DecimalField(max_digits=19, decimal_places=2)
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)  # its entry was voided or rejected

    class Meta:
        db_table = "assets_depreciation_run"
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "month"],
                condition=models.Q(cancelled_at__isnull=True),
                name="assets_month_once",
            ),
            models.CheckConstraint(condition=models.Q(total__gt=0), name="assets_run_total"),
        ]


class DepreciationRunLine(TenantOwned):
    run = models.ForeignKey(DepreciationRun, on_delete=models.PROTECT, related_name="lines")
    asset = models.ForeignKey(FixedAsset, on_delete=models.PROTECT, related_name="+")
    amount = models.DecimalField(max_digits=19, decimal_places=2)

    class Meta:
        db_table = "assets_depreciation_run_line"
        constraints = [
            models.UniqueConstraint(fields=["run", "asset"], name="assets_run_asset_once"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="assets_line_amount"),
        ]
