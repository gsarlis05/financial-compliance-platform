"""VIES statements recorded by the owner (V1-2g, #218), reconciled to Boxes 8A and 8B."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import fcp.core.ids

PROTECT = django.db.models.deletion.PROTECT


def _id() -> models.UUIDField:
    return models.UUIDField(default=fcp.core.ids.uuid7, editable=False, primary_key=True,
                            serialize=False)  # fmt: skip


def _user(**extra: bool) -> models.ForeignKey:  # type: ignore[type-arg]
    return models.ForeignKey(on_delete=PROTECT, related_name="+", to=settings.AUTH_USER_MODEL,
                             **extra)  # fmt: skip


class Migration(migrations.Migration):
    dependencies = [
        ("tax", "0006_imports_guard"),
        ("tenancy", "0009_one_person"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="VatViesStatement",
            fields=[
                ("id", _id()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("month", models.DateField()),
                ("kind", models.CharField(choices=[("ORIGINAL", "Original"),
                                                   ("CORRECTION", "Correction")],
                                          default="ORIGINAL", max_length=10)),  # fmt: skip
                ("filed_on", models.DateField()),
                ("reference", models.CharField(max_length=100)),
                ("note", models.CharField(blank=True, max_length=500)),
                ("voided_at", models.DateTimeField(blank=True, null=True)),
                ("void_reason", models.CharField(blank=True, max_length=500)),
                ("created_by", _user()),
                ("legal_entity", models.ForeignKey(on_delete=PROTECT, related_name="+",
                                                   to="tenancy.legalentity")),  # fmt: skip
                ("tenant", models.ForeignKey(on_delete=PROTECT, related_name="+",
                                             to="tenancy.tenant")),  # fmt: skip
                ("voided_by", _user(blank=True, null=True)),
            ],
            options={
                "db_table": "tax_vat_vies_statement",
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("voided_at__isnull", True), ("kind", "ORIGINAL")),
                        fields=("legal_entity", "month"),
                        name="tax_vies_one_original",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("month__day", 1)), name="tax_vies_month_start"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("reference", ""), _negated=True),
                        name="tax_vies_reference",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("voided_at__isnull", True),
                            models.Q(("voided_by__isnull", False),
                                     models.Q(("void_reason", ""), _negated=True)),
                            _connector="OR",
                        ),  # fmt: skip
                        name="tax_vies_voided",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="VatViesLine",
            fields=[
                ("id", _id()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("country", models.CharField(max_length=2)),
                ("vat_no", models.CharField(max_length=30)),
                ("goods", models.DecimalField(decimal_places=2, default=0, max_digits=19)),
                ("services", models.DecimalField(decimal_places=2, default=0, max_digits=19)),
                ("triangular", models.DecimalField(decimal_places=2, default=0, max_digits=19)),
                ("statement", models.ForeignKey(on_delete=PROTECT, related_name="lines",
                                                to="tax.vatviesstatement")),  # fmt: skip
                ("tenant", models.ForeignKey(on_delete=PROTECT, related_name="+",
                                             to="tenancy.tenant")),  # fmt: skip
            ],
            options={
                "db_table": "tax_vat_vies_line",
                "constraints": [
                    models.UniqueConstraint(fields=("statement", "country", "vat_no"),
                                            name="tax_vies_line_once"),  # fmt: skip
                    models.CheckConstraint(
                        condition=models.Q(("country__regex", "^[A-Z]{2}$"),
                                           models.Q(("vat_no", ""), _negated=True)),
                        name="tax_vies_line_party",
                    ),  # fmt: skip
                    models.CheckConstraint(
                        condition=models.Q(("goods", 0), ("services", 0), ("triangular", 0),
                                           _negated=True),
                        name="tax_vies_line_amount",
                    ),  # fmt: skip
                ],
            },
        ),
    ]
