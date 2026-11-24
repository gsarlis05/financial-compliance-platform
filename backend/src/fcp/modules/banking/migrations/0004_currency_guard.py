"""ISO 4217 guard on bank account currencies (M6F-1, #80)."""

from django.db import migrations

SQL = """
CREATE TRIGGER banking_account_currency
    BEFORE INSERT OR UPDATE OF currency ON banking_bank_account
    FOR EACH ROW EXECUTE FUNCTION core_currency_guard('currency');
"""
REVERSE = "DROP TRIGGER IF EXISTS banking_account_currency ON banking_bank_account;"


class Migration(migrations.Migration):
    dependencies = [("core_db", "0002_currencies"), ("banking", "0003_pending_tenants_function")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
