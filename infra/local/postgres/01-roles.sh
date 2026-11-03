#!/bin/sh
# Runs once when the local PostgreSQL volume is first created (docker-entrypoint-initdb.d).
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v owner_password="$POSTGRES_OWNER_PASSWORD" \
  -v app_password="$POSTGRES_APP_PASSWORD" \
  -v db_name="$POSTGRES_DB" \
  -f /fcp/create_roles.sql
# PostgreSQL 15+: the public schema belongs to the database owner (now fcp_owner).
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -c "ALTER SCHEMA public OWNER TO fcp_owner"
