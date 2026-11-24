"""Import records (V1-2f, #217): the customs declaration behind each import VAT claim."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import fcp.core.ids


class Migration(migrations.Migration):
    dependencies = [
        ("tax", "0004_four_steps_guards"),
        ("tenancy", "0009_one_person"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="VatImport",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=fcp.core.ids.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("entry_id", models.UUIDField()),
                ("customs_reference", models.CharField(max_length=50)),
                ("customs_date", models.DateField()),
                ("customs_value", models.DecimalField(decimal_places=2, max_digits=19)),
                ("import_vat", models.DecimalField(decimal_places=2, max_digits=19)),
                ("document_id", models.UUIDField()),
                ("document_name", models.CharField(max_length=200)),
                ("voided_at", models.DateTimeField(blank=True, null=True)),
                ("void_reason", models.CharField(blank=True, max_length=500)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "legal_entity",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="tenancy.legalentity",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="tenancy.tenant",
                    ),
                ),
                (
                    "voided_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "tax_vat_import",
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("voided_at__isnull", True)),
                        fields=("legal_entity", "customs_reference"),
                        name="tax_vat_import_reference_once",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("voided_at__isnull", True)),
                        fields=("legal_entity", "entry_id"),
                        name="tax_vat_import_entry_once",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("customs_value__gt", 0), ("import_vat__gt", 0)),
                        name="tax_vat_import_amounts",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("customs_reference", ""), _negated=True),
                        name="tax_vat_import_reference",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("voided_at__isnull", True),
                            models.Q(
                                ("voided_by__isnull", False),
                                models.Q(("void_reason", ""), _negated=True),
                            ),
                            _connector="OR",
                        ),
                        name="tax_vat_import_voided",
                    ),
                ],
            },
        ),
    ]
