"""Valuations of personal assets (M5-1, doc 11 §4.3).

A valuation is what the user says an asset (property, investments, a stake in their business) is
worth at a date. It has nature EXPECTED and is never posted to the ledger, so the books hold only
what happened. A correction supersedes the earlier value, which is kept (database trigger).
"""

from django.conf import settings
from django.db import models

from fcp.core.db.models import TenantOwned


class Valuation(TenantOwned):
    legal_entity = models.ForeignKey(
        "tenancy.LegalEntity", on_delete=models.PROTECT, related_name="+"
    )
    account_id = models.UUIDField()  # ledger_account of the same entity (composite FK)
    value_date = models.DateField()
    value = models.DecimalField(max_digits=19, decimal_places=2)
    nature = models.CharField(max_length=8, default="EXPECTED")
    note = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "personal_valuation"
        constraints = [
            models.UniqueConstraint(
                fields=["account_id", "value_date"],
                condition=models.Q(superseded_at__isnull=True),
                name="personal_valuation_one_current",
            ),
            models.CheckConstraint(
                condition=models.Q(value__gte=0), name="personal_valuation_not_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(nature="EXPECTED"), name="personal_valuation_nature"
            ),
        ]
