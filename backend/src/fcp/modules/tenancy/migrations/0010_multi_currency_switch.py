"""Foreign currency can be switched on per entity (V1-2h, #219; owner decision 2026-11-23)."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("tenancy", "0009_one_person"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="legalentity",
            name="tenancy_entity_multi_currency_off",
        ),
    ]
