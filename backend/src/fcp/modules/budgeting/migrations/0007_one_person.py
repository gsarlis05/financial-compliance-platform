"""One-person workspaces (V1-1, #207): a budget version approved by its submitter.

The version guard (migration 0002) lets ``self_approved`` change on approval, and a
self-approval is accepted only in a one-person workspace (``tenancy_self_approval_guard``, tenancy migration 0009).
"""

import importlib

from django.conf import settings
from django.db import migrations, models

_0002 = importlib.import_module(
    "fcp.modules.budgeting.migrations.0002_budgets_isolation_and_lifecycle"
)
OLD = _0002.VERSION_GUARD
NEW = OLD.replace("'approved_at', 'sod_applied']", "'approved_at', 'sod_applied', 'self_approved']")
if not (NEW != OLD):
    raise RuntimeError("the budget version guard no longer has the expected approval columns")
GUARD = """
CREATE TRIGGER budgeting_version_self_approval
    BEFORE INSERT OR UPDATE OF self_approved ON budgeting_version
    FOR EACH ROW EXECUTE FUNCTION tenancy_self_approval_guard();
"""
UNGUARD = "DROP TRIGGER IF EXISTS budgeting_version_self_approval ON budgeting_version;"
# Only the function is replaced; its trigger already exists.
NEW_FUNCTION = NEW[: NEW.index("CREATE TRIGGER budgeting_version_guard")]
OLD_FUNCTION = OLD[: OLD.index("CREATE TRIGGER budgeting_version_guard")]


class Migration(migrations.Migration):
    dependencies = [
        ("budgeting", "0006_variance_isolation"),
        ("tenancy", "0009_one_person"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="budgetversion",
            name="self_approved",
            field=models.BooleanField(default=False),
        ),
        migrations.AddConstraint(
            model_name="budgetversion",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("self_approved", False),
                    models.Q(
                        ("approved_by", models.F("submitted_by")),
                        ("sod_applied", False),
                    ),
                    _connector="OR",
                ),
                name="budgeting_version_self_approved",
            ),
        ),
        migrations.RunSQL(NEW_FUNCTION, OLD_FUNCTION),
        migrations.RunSQL(GUARD, UNGUARD),
    ]
