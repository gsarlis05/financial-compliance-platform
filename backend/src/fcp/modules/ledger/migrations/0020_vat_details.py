"""VAT details (V1-2b, #213): the VAT code's category, and on each line the tax point, the
deductible share and the blocked VAT. The catalogue is re-seeded with the categories and the new
codes (EU, reverse charge, imports, 3%), all unverified (#93)."""

from typing import Any

from django.db import migrations, models

from fcp.modules.ledger.vat import seed_catalogue


def seed(apps: Any, schema_editor: Any) -> None:
    del schema_editor
    seed_catalogue(apps.get_model("ledger", "VatCode"))


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0019_one_person"),
        ("registers", "0010_currency_guards"),
        ("tenancy", "0009_one_person"),
    ]

    operations = [
        migrations.AddField(
            model_name="journalline",
            name="tax_point",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="journalline",
            name="vat_blocked",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=19, null=True),
        ),
        migrations.AddField(
            model_name="journalline",
            name="vat_recovery_percent",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name="vatcode",
            name="category",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddConstraint(
            model_name="journalline",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("vat_recovery_percent__isnull", True),
                    models.Q(
                        ("vat_recovery_percent__gte", 0),
                        ("vat_recovery_percent__lte", 100),
                    ),
                    _connector="OR",
                ),
                name="ledger_line_vat_recovery_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="journalline",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("vat_blocked__isnull", True),
                    ("vat_blocked__gte", 0),
                    _connector="OR",
                ),
                name="ledger_line_vat_blocked_positive",
            ),
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
