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
