"""Seed the tax rule sets and refuse overlapping windows (M6F-2, #147).

Two rule sets of the same jurisdiction and tax may not cover the same day, so the rule in force
for a tax year is always unique. Seeding is idempotent (by id) and never changes the verification
fields: a professional's confirmation is recorded by its own migration (#154).
"""

from typing import Any

from django.db import migrations

from fcp.modules.taxrules.seed import seed_rules


def seed(apps: Any, schema_editor: Any) -> None:
    del schema_editor
    seed_rules(apps.get_model("taxrules", "TaxRuleSet"))


GUARD = """
CREATE OR REPLACE FUNCTION taxrules_no_overlap() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    IF EXISTS (
        SELECT 1 FROM taxrules_rule_set o
         WHERE o.id <> NEW.id AND o.jurisdiction = NEW.jurisdiction AND o.tax = NEW.tax
           AND daterange(o.effective_from, o.effective_to, '[]')
               && daterange(NEW.effective_from, NEW.effective_to, '[]')
    ) THEN
        RAISE EXCEPTION 'tax rule set % overlaps another for % %', NEW.id, NEW.jurisdiction,
            NEW.tax USING ERRCODE = 'exclusion_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER taxrules_no_overlap BEFORE INSERT OR UPDATE ON taxrules_rule_set
    FOR EACH ROW EXECUTE FUNCTION taxrules_no_overlap();
"""
REVERSE = """
DROP TRIGGER IF EXISTS taxrules_no_overlap ON taxrules_rule_set;
DROP FUNCTION IF EXISTS taxrules_no_overlap();
"""


class Migration(migrations.Migration):
    dependencies = [("taxrules", "0001_rule_sets")]
    operations = [
        migrations.RunSQL(GUARD, REVERSE),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
