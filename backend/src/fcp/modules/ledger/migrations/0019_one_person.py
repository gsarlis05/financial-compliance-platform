"""One-person workspaces (V1-1, #207): self-approved journal entries and period unlocks.

A row may be marked ``self_approved`` only in a one-person workspace
(``tenancy_self_approval_guard``,
tenancy migration 0009). The approver of an entry is never its preparer otherwise.
"""

from django.conf import settings
from django.db import migrations, models

SQL = """
CREATE TRIGGER ledger_entry_self_approval
    BEFORE INSERT OR UPDATE OF self_approved ON ledger_journal_entry
    FOR EACH ROW EXECUTE FUNCTION tenancy_self_approval_guard();
CREATE TRIGGER ledger_unlock_self_approval
    BEFORE INSERT OR UPDATE OF self_approved ON ledger_period_unlock
    FOR EACH ROW EXECUTE FUNCTION tenancy_self_approval_guard();
"""
REVERSE = """
DROP TRIGGER IF EXISTS ledger_unlock_self_approval ON ledger_period_unlock;
DROP TRIGGER IF EXISTS ledger_entry_self_approval ON ledger_journal_entry;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0018_currency_guards"),
        ("tenancy", "0009_one_person"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="periodunlock",
            name="ledger_unlock_first_approver_not_requester",
        ),
        migrations.AddField(
            model_name="journalentry",
            name="self_approved",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="periodunlock",
            name="self_approved",
            field=models.BooleanField(default=False),
        ),
        migrations.AddConstraint(
            model_name="journalentry",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("approved_by__isnull", True),
                    models.Q(("approved_by", models.F("prepared_by")), _negated=True),
                    ("self_approved", True),
                    _connector="OR",
                ),
                name="ledger_entry_approver_not_preparer",
            ),
        ),
        migrations.AddConstraint(
            model_name="journalentry",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("self_approved", False),
                    ("approved_by", models.F("prepared_by")),
                    _connector="OR",
                ),
                name="ledger_entry_self_approved_by_preparer",
            ),
        ),
        migrations.AddConstraint(
            model_name="periodunlock",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("first_approver__isnull", True),
                    models.Q(("first_approver", models.F("requested_by")), _negated=True),
                    models.Q(("second_approver__isnull", True), ("self_approved", True)),
                    _connector="OR",
                ),
                name="ledger_unlock_first_approver_not_requester",
            ),
        ),
        migrations.RunSQL(SQL, REVERSE),
    ]
