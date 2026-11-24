"""SQL functions used by every row-level security policy."""

from django.db import migrations

FUNCTIONS = """
CREATE OR REPLACE FUNCTION app_current_tenant() RETURNS uuid
    LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$;

CREATE OR REPLACE FUNCTION app_current_user() RETURNS uuid
    LANGUAGE sql STABLE PARALLEL SAFE AS
$$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$;
"""


class Migration(migrations.Migration):
    initial = True
    dependencies: list[tuple[str, str]] = []
    operations = [
        migrations.RunSQL(
            FUNCTIONS,
            reverse_sql="DROP FUNCTION IF EXISTS app_current_tenant(); "
            "DROP FUNCTION IF EXISTS app_current_user();",
        )
    ]
