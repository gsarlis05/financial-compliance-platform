"""Isolation for assumption-set loans (M6F-4, #149): FORCE row-level security, a composite
tenant key to the set, and changes only while the set is a draft (as for its values)."""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

GUARD = r"""
CREATE OR REPLACE FUNCTION projections_loan_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE
    set_status text;
BEGIN
    SELECT status INTO set_status FROM projections_assumption_set
     WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.assumption_set_id
                     ELSE NEW.assumption_set_id END;
    IF TG_OP = 'UPDATE' AND NEW.assumption_set_id <> OLD.assumption_set_id THEN
        RAISE EXCEPTION 'a loan cannot move to another assumption set'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF set_status IS DISTINCT FROM 'DRAFT' THEN
        RAISE EXCEPTION 'loans can change only while the assumption set is a draft'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER projections_loan_guard
    BEFORE INSERT OR UPDATE OR DELETE ON projections_assumption_loan
    FOR EACH ROW EXECUTE FUNCTION projections_loan_guard();
"""
REVERSE = """
DROP TRIGGER IF EXISTS projections_loan_guard ON projections_assumption_loan;
DROP FUNCTION IF EXISTS projections_loan_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("projections", "0005_assumption_loans")]
    operations = [
        *tenant_isolation("projections_assumption_loan"),
        composite_tenant_fk(
            "projections_assumption_loan", "assumption_set_id", "projections_assumption_set"
        ),
        migrations.RunSQL(GUARD, REVERSE),
    ]
