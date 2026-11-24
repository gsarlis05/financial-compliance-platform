"""One-person workspaces (V1-1, #207): a workspace KPI decided by its author.

The KPI guard (migration 0004) lets ``self_approved`` change with the decision, and a
self-decision is accepted only in a one-person workspace (``tenancy_self_approval_guard``).
"""

import importlib

from django.conf import settings
from django.db import migrations, models

_0004 = importlib.import_module("fcp.modules.kpi.migrations.0004_custom_isolation_and_guards")
_START = _0004.GUARDS.index("CREATE OR REPLACE FUNCTION kpi_custom_guard()")
_END = _0004.GUARDS.index("CREATE TRIGGER kpi_custom_guard")
OLD_FUNCTION = _0004.GUARDS[_START:_END]
NEW_FUNCTION = OLD_FUNCTION.replace("'decision_comment']", "'decision_comment', 'self_approved']")
if not (NEW_FUNCTION.count("'self_approved'") == 2):
    raise RuntimeError("the KPI guard no longer has the expected decision columns")
GUARD = """
CREATE TRIGGER kpi_custom_self_approval
    BEFORE INSERT OR UPDATE OF self_approved ON kpi_custom
    FOR EACH ROW EXECUTE FUNCTION tenancy_self_approval_guard();
"""
UNGUARD = "DROP TRIGGER IF EXISTS kpi_custom_self_approval ON kpi_custom;"


class Migration(migrations.Migration):
    dependencies = [
        ("kpi", "0005_core_library_1_1"),
        ("tenancy", "0009_one_person"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="customkpi",
            name="kpi_custom_sod",
        ),
        migrations.AddField(
            model_name="customkpi",
            name="self_approved",
            field=models.BooleanField(default=False),
        ),
        migrations.AddConstraint(
            model_name="customkpi",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("scope", "WORKSPACE"),
                        ("status__in", ["APPROVED", "REJECTED"]),
                        _negated=True,
                    ),
                    models.Q(("decided_by", models.F("owner")), _negated=True),
                    ("self_approved", True),
                    _connector="OR",
                ),
                name="kpi_custom_sod",
            ),
        ),
        migrations.AddConstraint(
            model_name="customkpi",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("self_approved", False),
                    models.Q(("decided_by", models.F("owner")), ("scope", "WORKSPACE")),
                    _connector="OR",
                ),
                name="kpi_custom_self_approved",
            ),
        ),
        migrations.RunSQL(NEW_FUNCTION, OLD_FUNCTION),
        migrations.RunSQL(GUARD, UNGUARD),
    ]
