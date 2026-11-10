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


class BudgetAmount(TenantOwned):
    """How much a category should be each month from ``effective_from`` on (M5-2). A new amount
    from the same month supersedes the earlier one, which is kept; the amount in force for a
    month is the latest one that started on or before it. Zero ends a budget."""

    legal_entity = models.ForeignKey(
        "tenancy.LegalEntity", on_delete=models.PROTECT, related_name="+"
    )
    account_id = models.UUIDField()  # an income or spending category of the same entity
    effective_from = models.DateField()  # first day of a month
    monthly_amount = models.DecimalField(max_digits=19, decimal_places=2)
    nature = models.CharField(max_length=8, default="BUDGET")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "personal_budget_amount"
        constraints = [
            models.UniqueConstraint(
                fields=["account_id", "effective_from"],
                condition=models.Q(superseded_at__isnull=True),
                name="personal_budget_one_current",
            ),
            models.CheckConstraint(
                condition=models.Q(monthly_amount__gte=0), name="personal_budget_not_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(nature="BUDGET"), name="personal_budget_nature"
            ),
        ]


class PersonalGoal(TenantOwned):
    """A personal goal (M5-2): save a total, keep an emergency fund of some months of spending,
    or pay debts down, by a date. Goals never change; a different goal is a new one, and an old
    one can be retired (database trigger)."""

    class Kind(models.TextChoices):
        SAVINGS = "SAVINGS"
        EMERGENCY_FUND = "EMERGENCY_FUND"
        DEBT_PAYOFF = "DEBT_PAYOFF"

    legal_entity = models.ForeignKey(
        "tenancy.LegalEntity", on_delete=models.PROTECT, related_name="+"
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    name = models.CharField(max_length=120)
    account_ids = models.JSONField(default=list)  # money accounts it counts
    target_amount = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    months = models.PositiveSmallIntegerField(null=True, blank=True)  # emergency fund
    target_date = models.DateField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "personal_goal"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind__in=["SAVINGS", "EMERGENCY_FUND", "DEBT_PAYOFF"]),
                name="personal_goal_kind",
            ),
            models.CheckConstraint(
                condition=models.Q(target_amount__gte=0), name="personal_goal_target"
            ),
            models.CheckConstraint(
                condition=~models.Q(kind="EMERGENCY_FUND") | models.Q(months__gte=1),
                name="personal_goal_months",
            ),
        ]


class CounterpartLink(TenantOwned):
    """An opt-in link from the personal books to one account of a business the same person
    belongs to (M5-3, doc 11 §4.2), for example the director's loan account. It only stores the
    reference; business figures are read by the person, in the business workspace, with their own
    permissions there. A link can be revoked, not edited (database trigger)."""

    legal_entity = models.ForeignKey(
        "tenancy.LegalEntity", on_delete=models.PROTECT, related_name="+"
    )
    business_slug = models.CharField(max_length=64)
    business_entity_id = models.UUIDField()
    business_account_id = models.UUIDField()
    label = models.CharField(max_length=200)  # e.g. "Demo Trading Ltd · 2020 Director loans"
    account_id = models.UUIDField()  # personal money account the money arrives in
    category_id = models.UUIDField()  # personal income category
    since = models.DateField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "personal_counterpart_link"


class CounterpartDecision(TenantOwned):
    """What the person decided about one suggested business payment: recorded in the personal
    books (with the entry it became) or dismissed. One decision per business entry and link;
    decisions are never changed or deleted (append-only)."""

    class Decision(models.TextChoices):
        CONFIRMED = "CONFIRMED"
        DISMISSED = "DISMISSED"

    link = models.ForeignKey(CounterpartLink, on_delete=models.PROTECT, related_name="+")
    business_entry_id = models.UUIDField()
    decision = models.CharField(max_length=10, choices=Decision.choices)
    amount = models.DecimalField(max_digits=19, decimal_places=2)
    entry_date = models.DateField()
    personal_entry_id = models.UUIDField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "personal_counterpart_decision"
        constraints = [
            models.UniqueConstraint(
                fields=["link", "business_entry_id"], name="personal_counterpart_once"
            ),
            models.CheckConstraint(
                condition=models.Q(decision__in=["CONFIRMED", "DISMISSED"]),
                name="personal_counterpart_decision_kind",
            ),
            models.CheckConstraint(
                condition=models.Q(decision="DISMISSED")
                | models.Q(personal_entry_id__isnull=False),
                name="personal_counterpart_confirmed_entry",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="personal_counterpart_amount"
            ),
        ]
