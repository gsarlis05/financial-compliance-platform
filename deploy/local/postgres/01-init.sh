#!/bin/sh
# Runs once, when the database volume is first created (docker-entrypoint-initdb.d).
# The platform's roles (scripts/db/create_roles.sql) and a separate database for the sign-in
# service (Keycloak), owned by its own role.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v owner_password="$POSTGRES_OWNER_PASSWORD" \
  -v app_password="$POSTGRES_APP_PASSWORD" \
  -v db_name="$POSTGRES_DB" \
  -f /fcp/create_roles.sql
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -c "ALTER SCHEMA public OWNER TO fcp_owner"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v kc_password="$KEYCLOAK_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE keycloak LOGIN PASSWORD %L', :'kc_password') \gexec
CREATE DATABASE keycloak OWNER keycloak;
SQL
