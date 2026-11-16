"""ISO 4217 currencies as reference data, and the guard every currency column uses (M6F-1, #80).

- ``core_currency``: the currencies the platform supports (code, ISO numeric code, minor units).
  Global, read-only for the runtime role, changed only by migrations. The list matches
  ``fcp.core.money.currency``; a test keeps the two equal.
- ``core_currency_guard()``: a trigger function that refuses a value in the column named by its
  first argument unless it is a code in ``core_currency``. A second argument ``'blank'`` lets the
  column be empty (e.g. an account that accepts any currency).

Module migrations attach the guard to their currency columns.
"""

from django.db import migrations

SQL = """
CREATE TABLE core_currency (
    code char(3) PRIMARY KEY CHECK (code ~ '^[A-Z]{3}$'),
    numeric_code char(3) NOT NULL UNIQUE CHECK (numeric_code ~ '^[0-9]{3}$'),
    minor_units smallint NOT NULL CHECK (minor_units BETWEEN 0 AND 4)
);
-- code, ISO numeric code, minor units (ISO 4217)
INSERT INTO core_currency (code, numeric_code, minor_units) VALUES
    ('AED', '784', 2), ('BGN', '975', 2), ('BHD', '048', 3), ('CHF', '756', 2),
    ('CNY', '156', 2), ('CZK', '203', 2), ('DKK', '208', 2), ('EUR', '978', 2),
    ('GBP', '826', 2), ('HUF', '348', 2), ('ILS', '376', 2), ('JPY', '392', 0),
    ('KWD', '414', 3), ('NOK', '578', 2), ('PLN', '985', 2), ('RON', '946', 2),
    ('RUB', '643', 2), ('SEK', '752', 2), ('USD', '840', 2);

CREATE OR REPLACE FUNCTION core_currency_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE
    value text := to_jsonb(NEW) ->> TG_ARGV[0];
BEGIN
    IF value IS NULL OR (value = '' AND TG_NARGS > 1 AND TG_ARGV[1] = 'blank') THEN
        RETURN NEW;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM core_currency WHERE code = value) THEN
        RAISE EXCEPTION '% is not a supported ISO 4217 currency code', quote_literal(value)
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;
"""

REVERSE = """
DROP FUNCTION IF EXISTS core_currency_guard();
DROP TABLE IF EXISTS core_currency;
"""


class Migration(migrations.Migration):
    dependencies = [("core_db", "0001_rls_functions")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
