"""Foreign-currency lines (V1-2h, #219): the rate's date and time and its source; the entity's
exchange-differences account."""

import django.db.models.deletion
from django.db import migrations, models

from fcp.core.db.operations import composite_tenant_fk


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0020_vat_details"),
        ("registers", "0011_vat_details"),
        ("tenancy", "0010_multi_currency_switch"),
    ]

    operations = [
        migrations.AddField(
            model_name="journalline",
            name="rate_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="journalline",
            name="rate_source",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="ledgersettings",
            name="fx_account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="ledger.account",
            ),
        ),
        migrations.AddConstraint(
            model_name="journalline",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("txn_currency__isnull", True),
                    models.Q(
                        ("rate_at__isnull", False),
                        models.Q(("rate_source", ""), _negated=True),
                    ),
                    _connector="OR",
                ),
                name="ledger_line_txn_rate_source",
            ),
        ),
        composite_tenant_fk("ledger_settings", "fx_account_id", "ledger_account"),
    ]
