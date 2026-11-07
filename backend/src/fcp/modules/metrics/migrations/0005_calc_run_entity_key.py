"""A key on (legal entity, run) so that other modules can reference a run of the same entity
(goal baselines and evaluations, M4-6)."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("metrics", "0004_calc_runs_isolation")]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE metrics_calc_run ADD CONSTRAINT metrics_calc_run_entity_id_key "
            "UNIQUE (legal_entity_id, id)",
            "ALTER TABLE metrics_calc_run DROP CONSTRAINT metrics_calc_run_entity_id_key",
        ),
    ]
