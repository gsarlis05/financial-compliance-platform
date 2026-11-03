"""Row-level security for integrity check results."""

from django.db import migrations

from fcp.core.db.operations import tenant_isolation


class Migration(migrations.Migration):
    dependencies = [("ledger", "0007_integritycheckrun")]
    operations = [*tenant_isolation("ledger_integrity_check_run")]
