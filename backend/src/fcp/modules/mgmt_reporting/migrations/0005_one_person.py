"""One-person workspaces (V1-1, #207): a report pack finalised by its preparer.

The pack guard (migration 0002) accepts a final pack whose reviewer is its preparer only when the
pack is marked self-approved in a one-person workspace; a draft or a pack in review is never
marked so.
"""

import importlib

from django.conf import settings
from django.db import migrations, models

_0002 = importlib.import_module("fcp.modules.mgmt_reporting.migrations.0002_isolation")
OLD_FUNCTION = _0002.GUARDS[: _0002.GUARDS.index("CREATE TRIGGER mgmt_reporting_pack_guard")]
NEW_FUNCTION = (
    OLD_FUNCTION.replace(
        "OR NEW.finalised_at IS NOT NULL OR NEW.superseded_at IS NOT NULL THEN\n"
        "            RAISE EXCEPTION 'a report pack starts as a draft'",
        "OR NEW.finalised_at IS NOT NULL OR NEW.superseded_at IS NOT NULL OR NEW.self_approved "
        "THEN\n            RAISE EXCEPTION 'a report pack starts as a draft'",
    )
    .replace(
        "AND NEW.finalised_at IS NULL AND NEW.superseded_at IS NULL THEN\n"
        "            RETURN NEW;  -- editing or regenerating a draft",
        "AND NEW.finalised_at IS NULL AND NEW.superseded_at IS NULL AND NOT NEW.self_approved "
        "THEN\n            RETURN NEW;  -- editing or regenerating a draft",
    )
    .replace(
        "AND NEW.reviewed_by_id IS NULL AND NEW.finalised_at IS NULL THEN",
        "AND NEW.reviewed_by_id IS NULL AND NEW.finalised_at IS NULL AND NOT NEW.self_approved THEN",
    )
    .replace(
        "IF NEW.status = 'DRAFT' AND NEW.submitted_at IS NULL AND NEW.finalised_at IS NULL THEN",
        "IF NEW.status = 'DRAFT' AND NEW.submitted_at IS NULL AND NEW.finalised_at IS NULL\n"
        "           AND NOT NEW.self_approved THEN",
    )
    .replace(
        "IF NEW.reviewed_by_id = NEW.created_by_id THEN",
        "IF NEW.reviewed_by_id = NEW.created_by_id\n"
        "               AND NOT (NEW.self_approved AND tenancy_one_person(NEW.tenant_id)) THEN",
    )
)
if not (NEW_FUNCTION.count("self_approved") == 5):
    raise RuntimeError("the report pack guard no longer has the expected rules")


class Migration(migrations.Migration):
    dependencies = [
        ("mgmt_reporting", "0004_notes_isolation"),
        ("tenancy", "0009_one_person"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="reportpack",
            name="self_approved",
            field=models.BooleanField(default=False),
        ),
        migrations.AddConstraint(
            model_name="reportpack",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("self_approved", False),
                    ("reviewed_by", models.F("created_by")),
                    _connector="OR",
                ),
                name="mgmt_reporting_pack_self_approved",
            ),
        ),
        migrations.RunSQL(NEW_FUNCTION, OLD_FUNCTION),
    ]
