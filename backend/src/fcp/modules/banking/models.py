"""Banking: bank accounts, statement imports, statement lines and reconciliations (M2-5).

- ``BankAccount`` links a bank account (IBAN) to its ledger account (an asset, e.g. 1300 Bank).
- ``StatementImport`` is one uploaded file. Its SHA-256 is unique per bank account, so the same
  file is never imported twice (a failed import may be retried). The raw file is kept as
  evidence (until documents move to object storage in M2-4). Imports are processed by a worker,
  not in the request (ADR-0015).
- ``StatementLine`` is one booked transaction. ``line_hash`` (date, amount, bank reference or
  text, and its occurrence within the file) is unique per bank account, so overlapping statements
  never create duplicates (AC-M2-5). A line is matched to at most one posted ledger line on the
  bank's ledger account, and a ledger line to at most one statement line.
- ``Reconciliation`` records that, at a date, the ledger balance of the bank account equals the
  statement balance. It is append-only; the latest one is the "last reconciled" date.
"""

from django.conf import settings
from django.db import models

from fcp.core.db.models import TenantOwned

LEGAL_ENTITY = "tenancy.LegalEntity"


class BankAccount(TenantOwned):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        INACTIVE = "INACTIVE"

    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    ledger_account = models.ForeignKey("ledger.Account", on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=100)
    iban = models.CharField(max_length=34, blank=True)
    currency = models.CharField(max_length=3, default="EUR")
    csv_mapping = models.JSONField(null=True, blank=True, help_text="Saved CSV column mapping")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "banking_bank_account"
        constraints = [
            models.UniqueConstraint(
                fields=["ledger_account"], name="banking_account_one_per_ledger_account"
            ),
        ]


class StatementImport(TenantOwned):
    class Format(models.TextChoices):
        CAMT053 = "CAMT053"
        CSV = "CSV"

    class Status(models.TextChoices):
        PENDING = "PENDING"
        DONE = "DONE"
        FAILED = "FAILED"

    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="+")
    format = models.CharField(max_length=8, choices=Format.choices)
    filename = models.CharField(max_length=200)
    file_sha256 = models.CharField(max_length=64)
    content = models.BinaryField()
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    error = models.CharField(max_length=500, blank=True)
    statement_id = models.CharField(max_length=100, blank=True)
    opening_balance = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    closing_balance = models.DecimalField(max_digits=19, decimal_places=4, null=True, blank=True)
    closing_date = models.DateField(null=True, blank=True)
    lines_created = models.PositiveIntegerField(default=0)
    lines_duplicate = models.PositiveIntegerField(default=0)
    lines_skipped = models.PositiveIntegerField(default=0, help_text="Pending (not booked)")
    processed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "banking_statement_import"
        constraints = [
            # A failed import does not count: the same file may be retried (e.g. after fixing
            # the CSV column mapping).
            models.UniqueConstraint(
                fields=["bank_account", "file_sha256"],
                condition=~models.Q(status="FAILED"),
                name="banking_import_file_once",
            ),
        ]
        indexes = [models.Index(fields=["status", "created_at"])]


class StatementLine(TenantOwned):
    class Status(models.TextChoices):
        UNMATCHED = "UNMATCHED"
        MATCHED = "MATCHED"
        IGNORED = "IGNORED"

    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="+")
    statement_import = models.ForeignKey(
        StatementImport, on_delete=models.PROTECT, related_name="+"
    )
    booking_date = models.DateField()
    value_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=19, decimal_places=4)
    description = models.CharField(max_length=500, blank=True)
    counterparty_name = models.CharField(max_length=500, blank=True)
    reference = models.CharField(max_length=500, blank=True)
    bank_ref = models.CharField(max_length=500, blank=True)
    line_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UNMATCHED)
    matched_line = models.OneToOneField(
        "ledger.JournalLine", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    note = models.CharField(max_length=500, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "banking_statement_line"
        constraints = [
            models.UniqueConstraint(fields=["bank_account", "line_hash"], name="banking_line_once"),
            models.CheckConstraint(
                condition=(
                    models.Q(status="MATCHED", matched_line__isnull=False)
                    | (~models.Q(status="MATCHED") & models.Q(matched_line__isnull=True))
                ),
                name="banking_line_match_consistent",
            ),
        ]
        indexes = [models.Index(fields=["bank_account", "status", "booking_date"])]


class Reconciliation(TenantOwned):
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="+")
    as_of = models.DateField()
    statement_balance = models.DecimalField(max_digits=19, decimal_places=4)
    ledger_balance = models.DecimalField(max_digits=19, decimal_places=4)
    unmatched_lines = models.PositiveIntegerField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "banking_reconciliation"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(statement_balance=models.F("ledger_balance")),
                name="banking_reconciliation_agrees",
            ),
        ]
