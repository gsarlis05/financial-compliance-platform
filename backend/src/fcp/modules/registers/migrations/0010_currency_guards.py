"""ISO 4217 guards on obligation and debt currencies (M6F-1, #80)."""

from django.db import migrations

SQL = """
CREATE TRIGGER registers_obligation_currency
    BEFORE INSERT OR UPDATE OF currency ON registers_recurring_obligation
    FOR EACH ROW EXECUTE FUNCTION core_currency_guard('currency');
CREATE TRIGGER registers_debt_currency
    BEFORE INSERT OR UPDATE OF currency ON registers_debt_instrument
    FOR EACH ROW EXECUTE FUNCTION core_currency_guard('currency');
"""
REVERSE = """
DROP TRIGGER IF EXISTS registers_obligation_currency ON registers_recurring_obligation;
DROP TRIGGER IF EXISTS registers_debt_currency ON registers_debt_instrument;
"""


class Migration(migrations.Migration):
    dependencies = [("core_db", "0002_currencies"), ("registers", "0009_days_late_override")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
