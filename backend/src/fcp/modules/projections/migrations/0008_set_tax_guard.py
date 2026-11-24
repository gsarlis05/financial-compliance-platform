"""The set guard also covers its tax position (M6F-5, #150): the losses brought forward, the
provisional tax paid and the deferred-tax-asset choice change only while the set is a draft."""

from django.db import migrations

GUARD = r"""
CREATE OR REPLACE FUNCTION projections_set_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE
    frozen CONSTANT text[] := ARRAY['name', 'note', 'status', 'approved_by_id', 'approved_at',
                                    'superseded_at', 'tax_losses_bf', 'tax_paid_ytd',
                                    'recognise_loss_dta'];
    same_tax boolean := NEW.tax_losses_bf = OLD.tax_losses_bf
                        AND NEW.tax_paid_ytd = OLD.tax_paid_ytd
                        AND NEW.recognise_loss_dta = OLD.recognise_loss_dta;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'assumption sets are kept'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF (to_jsonb(NEW) - frozen) IS DISTINCT FROM (to_jsonb(OLD) - frozen) THEN
        RAISE EXCEPTION 'the horizon and origin of an assumption set never change'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.status = 'DRAFT' AND NEW.status = 'DRAFT'
       AND NEW.approved_by_id IS NULL AND NEW.approved_at IS NULL AND NEW.superseded_at IS NULL THEN
        RETURN NEW;  -- renaming a draft, or changing its tax position
    END IF;
    IF OLD.status = 'DRAFT' AND NEW.status = 'APPROVED' AND same_tax
       AND NEW.name = OLD.name AND NEW.note = OLD.note AND NEW.superseded_at IS NULL THEN
        RETURN NEW;
    END IF;
    IF OLD.status = 'APPROVED' AND NEW.status = 'SUPERSEDED' AND NEW.superseded_at IS NOT NULL
       AND same_tax AND NEW.name = OLD.name AND NEW.note = OLD.note
       AND NEW.approved_by_id = OLD.approved_by_id AND NEW.approved_at = OLD.approved_at THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'an approved assumption set never changes; revise it as a new version'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;
"""


class Migration(migrations.Migration):
    dependencies = [("projections", "0007_set_tax_position")]
    operations = [migrations.RunSQL(GUARD, migrations.RunSQL.noop)]
