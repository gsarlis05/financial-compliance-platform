"""ISO 4217 guards on an entity's functional and reporting currencies (M6F-1, #80)."""

from django.db import migrations

SQL = """
CREATE TRIGGER tenancy_entity_functional_currency
    BEFORE INSERT OR UPDATE OF functional_currency ON tenancy_legal_entity
    FOR EACH ROW EXECUTE FUNCTION core_currency_guard('functional_currency');
CREATE TRIGGER tenancy_entity_reporting_currency
    BEFORE INSERT OR UPDATE OF reporting_currency ON tenancy_legal_entity
    FOR EACH ROW EXECUTE FUNCTION core_currency_guard('reporting_currency');
"""
REVERSE = """
DROP TRIGGER IF EXISTS tenancy_entity_functional_currency ON tenancy_legal_entity;
DROP TRIGGER IF EXISTS tenancy_entity_reporting_currency ON tenancy_legal_entity;
"""


class Migration(migrations.Migration):
    dependencies = [("core_db", "0002_currencies"), ("tenancy", "0007_currency_foundation")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
