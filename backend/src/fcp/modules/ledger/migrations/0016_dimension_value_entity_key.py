"""A dimension value is identified within its legal entity, so that other modules' tables (budget
lines, M4-1) can reference it with a composite foreign key that stays inside one entity."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("ledger", "0015_year_end_close")]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE ledger_dimension_value ADD CONSTRAINT ledger_dimension_value_entity_id_key "
            "UNIQUE (legal_entity_id, id)",
            reverse_sql="ALTER TABLE ledger_dimension_value "
            "DROP CONSTRAINT ledger_dimension_value_entity_id_key",
        )
    ]
