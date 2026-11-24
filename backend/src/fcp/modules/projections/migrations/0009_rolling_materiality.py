"""Rolling forecasts re-run on material changes (M6F-6, #151): the regular interval and the
materiality threshold of postings."""

from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("projections", "0008_set_tax_guard")]

    operations = [
        migrations.AddField(
            model_name="rollingforecast",
            name="interval_minutes",
            field=models.PositiveSmallIntegerField(default=60),
        ),
        migrations.AddField(
            model_name="rollingforecast",
            name="materiality",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=19, null=True),
        ),
        migrations.AddConstraint(
            model_name="rollingforecast",
            constraint=models.CheckConstraint(
                condition=models.Q(interval_minutes__in=[15, 30, 60, 120, 240, 480, 1440]),
                name="projections_rolling_interval",
            ),
        ),
        migrations.AddConstraint(
            model_name="rollingforecast",
            constraint=models.CheckConstraint(
                condition=models.Q(materiality__isnull=True)
                | models.Q(materiality__gte=Decimal(0)),
                name="projections_rolling_materiality",
            ),
        ),
    ]
