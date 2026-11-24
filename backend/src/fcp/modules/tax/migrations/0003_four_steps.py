"""Four steps for a VAT report (V1-2d, #215): Draft, Reviewed, Finalised, Filed; manual
adjustments; the inclusion of each line in a return.

The single sign-off of V1-2a both reviewed and finalised a report, by someone other than its
preparer. Reports signed off before this migration are therefore finalised, reviewed and finalised
by the same person at the same time. The report guard is dropped here and replaced in 0004.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import fcp.core.ids

# The table owner reads every tenant's rows only while row security is not forced; both steps run
# in this migration's transaction.
SIGNED_OFF_IS_FINALISED = """
DROP TRIGGER IF EXISTS tax_vat_report_guard ON tax_vat_report;
ALTER TABLE tax_vat_report NO FORCE ROW LEVEL SECURITY;
UPDATE tax_vat_report SET reviewed_by_id = finalised_by_id, reviewed_at = finalised_at
 WHERE finalised_by_id IS NOT NULL;
UPDATE tax_vat_report SET status = 'FINALISED' WHERE status = 'SIGNED_OFF';
ALTER TABLE tax_vat_report FORCE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("tax", "0002_isolation"),
        ("tenancy", "0009_one_person"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="VatAdjustment",
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
                ("box", models.CharField(max_length=3)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=19)),
                ("reason", models.CharField(max_length=500)),
                ("evidence", models.CharField(max_length=500)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PROPOSED", "Proposed"),
                            ("APPROVED", "Approved"),
                            ("REJECTED", "Rejected"),
                        ],
                        default="PROPOSED",
                        max_length=8,
                    ),
                ),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_note", models.CharField(blank=True, max_length=500)),
                ("self_approved", models.BooleanField(default=False)),
            ],
            options={
                "db_table": "tax_vat_adjustment",
            },
        ),
        migrations.CreateModel(
            name="VatInclusion",
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
                ("line_id", models.UUIDField()),
                ("entry_id", models.UUIDField()),
                ("active", models.BooleanField(default=True)),
            ],
            options={
                "db_table": "tax_vat_inclusion",
            },
        ),
        migrations.RemoveConstraint(
            model_name="vatreport",
            name="tax_vat_report_one_draft",
        ),
        migrations.RemoveConstraint(
            model_name="vatreport",
            name="tax_vat_report_signed",
        ),
        migrations.RemoveConstraint(
            model_name="vatreport",
            name="tax_vat_report_sod",
        ),
        migrations.RemoveConstraint(
            model_name="vatreport",
            name="tax_vat_report_self_approved",
        ),
        migrations.RenameField(
            model_name="vatreport",
            old_name="signed_off_at",
            new_name="finalised_at",
        ),
        migrations.RenameField(
            model_name="vatreport",
            old_name="signed_off_by",
            new_name="finalised_by",
        ),
        migrations.AddField(
            model_name="vatreport",
            name="filing_evidence",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="vatreport",
            name="review_note",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="vatreport",
            name="reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="vatreport",
            name="reviewed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="vatreport",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "Draft"),
                    ("REVIEWED", "Reviewed"),
                    ("FINALISED", "Finalised"),
                    ("FILED", "Filed"),
                    ("SUPERSEDED", "Superseded"),
                ],
                default="DRAFT",
                max_length=10,
            ),
        ),
        migrations.RunSQL(SIGNED_OFF_IS_FINALISED, migrations.RunSQL.noop),
        migrations.AddConstraint(
            model_name="vatreport",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status__in", ["DRAFT", "REVIEWED"])),
                fields=("legal_entity", "period_start"),
                name="tax_vat_report_one_open",
            ),
        ),
        migrations.AddConstraint(
            model_name="vatreport",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("status", "DRAFT"),
                    models.Q(("reviewed_at__isnull", False), ("reviewed_by__isnull", False)),
                    _connector="OR",
                ),
                name="tax_vat_report_reviewed",
            ),
        ),
        migrations.AddConstraint(
            model_name="vatreport",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("status__in", ["DRAFT", "REVIEWED"]),
                    models.Q(("finalised_at__isnull", False), ("finalised_by__isnull", False)),
                    _connector="OR",
                ),
                name="tax_vat_report_finalised",
            ),
        ),
        migrations.AddConstraint(
            model_name="vatreport",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("reviewed_by__isnull", True),
                        models.Q(("reviewed_by", models.F("created_by")), _negated=True),
                        ("self_approved", True),
                        _connector="OR",
                    ),
                    models.Q(
                        ("finalised_by__isnull", True),
                        models.Q(("finalised_by", models.F("created_by")), _negated=True),
                        ("self_approved", True),
                        _connector="OR",
                    ),
                ),
                name="tax_vat_report_sod",
            ),
        ),
        migrations.AddConstraint(
            model_name="vatreport",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("self_approved", False),
                    ("reviewed_by", models.F("created_by")),
                    ("finalised_by", models.F("created_by")),
                    _connector="OR",
                ),
                name="tax_vat_report_self_approved",
            ),
        ),
        migrations.AddField(
            model_name="vatadjustment",
            name="created_by",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="vatadjustment",
            name="decided_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="vatadjustment",
            name="report",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="adjustments",
                to="tax.vatreport",
            ),
        ),
        migrations.AddField(
            model_name="vatadjustment",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="tenancy.tenant",
            ),
        ),
        migrations.AddField(
            model_name="vatinclusion",
            name="report",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="tax.vatreport",
            ),
        ),
        migrations.AddField(
            model_name="vatinclusion",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="tenancy.tenant",
            ),
        ),
        migrations.AddConstraint(
            model_name="vatadjustment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "box__in",
                        ("1", "2", "4", "6", "7", "8A", "8B", "9", "10", "11A", "11B"),
                    )
                ),
                name="tax_vat_adj_box",
            ),
        ),
        migrations.AddConstraint(
            model_name="vatadjustment",
            constraint=models.CheckConstraint(
                condition=models.Q(("amount", 0), _negated=True),
                name="tax_vat_adj_amount",
            ),
        ),
        migrations.AddConstraint(
            model_name="vatadjustment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("reason", ""), _negated=True),
                    models.Q(("evidence", ""), _negated=True),
                ),
                name="tax_vat_adj_reasoned",
            ),
        ),
        migrations.AddConstraint(
            model_name="vatadjustment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("status", "PROPOSED"),
                    models.Q(("decided_at__isnull", False), ("decided_by__isnull", False)),
                    _connector="OR",
                ),
                name="tax_vat_adj_decided",
            ),
        ),
        migrations.AddConstraint(
            model_name="vatadjustment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("status", "APPROVED"), _negated=True),
                    models.Q(("decided_by", models.F("created_by")), _negated=True),
                    ("self_approved", True),
                    _connector="OR",
                ),
                name="tax_vat_adj_sod",
            ),
        ),
        migrations.AddConstraint(
            model_name="vatadjustment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("self_approved", False),
                    models.Q(("decided_by", models.F("created_by")), ("status", "APPROVED")),
                    _connector="OR",
                ),
                name="tax_vat_adj_self_approved",
            ),
        ),
        migrations.AddConstraint(
            model_name="vatinclusion",
            constraint=models.UniqueConstraint(
                fields=("report", "line_id"), name="tax_vat_inclusion_once"
            ),
        ),
        migrations.AddConstraint(
            model_name="vatinclusion",
            constraint=models.UniqueConstraint(
                condition=models.Q(("active", True)),
                fields=("tenant", "line_id"),
                name="tax_vat_inclusion_one_return",
            ),
        ),
    ]
