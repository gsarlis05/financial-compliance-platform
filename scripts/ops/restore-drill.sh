#!/usr/bin/env bash
# Backup and restore drill against the LOCAL stack (M5-5, docs/runbooks/backup-restore-drill.md).
#
# 1. Takes a consistent backup of the local database (pg_dump, custom format, one snapshot).
# 2. Restores it into a scratch database next to it.
# 3. Proves the restore: the same row count in every table as the snapshot, and the
#    application's own checks pass on the restored copy (audit chain, ledger integrity, actuals).
# 4. Removes the scratch database and the backup file.
#
# It never touches a deployed environment and never changes the source database.
set -euo pipefail

cd "$(dirname "$0")/../.."
set -a
# shellcheck disable=SC1091
. ./.env
set +a

SCRATCH="fcp_restore_drill"
PG=(docker compose exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres)
psql_in() { "${PG[@]}" psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" "$@"; }
started=$(date +%s)

COUNTS="SELECT table_name || ' ' ||
  (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM public.%I', table_name),
                                       false, true, '')))[1]::text
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name"

cleanup() {
  psql_in -d postgres -c "DROP DATABASE IF EXISTS $SCRATCH" >/dev/null 2>&1 || true
  "${PG[@]}" rm -f /tmp/fcp-drill.dump /tmp/fcp-drill.source /tmp/fcp-drill.restored >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

echo "1/4 Backup of '$POSTGRES_DB' (one snapshot for the dump and the row counts)"
psql_in -d "$POSTGRES_DB" -At <<SQL
BEGIN ISOLATION LEVEL REPEATABLE READ;
SELECT pg_export_snapshot() AS snap \gset
\setenv FCP_SNAPSHOT :snap
\! pg_dump -Fc --snapshot="\$FCP_SNAPSHOT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /tmp/fcp-drill.dump
\o /tmp/fcp-drill.source
$COUNTS;
\o
COMMIT;
SQL
size=$("${PG[@]}" sh -c 'wc -c < /tmp/fcp-drill.dump')
backed_up=$(date +%s)
echo "    backup file: $size bytes, $((backed_up - started)) s"

echo "2/4 Restore into the scratch database '$SCRATCH'"
psql_in -d postgres -c "CREATE DATABASE $SCRATCH"
"${PG[@]}" pg_restore --exit-on-error -U "$POSTGRES_USER" -d "$SCRATCH" /tmp/fcp-drill.dump
restored=$(date +%s)
echo "    restored in $((restored - backed_up)) s"

echo "3/4 Compare row counts, table by table"
psql_in -d "$SCRATCH" -At -o /tmp/fcp-drill.restored -c "$COUNTS"
if ! "${PG[@]}" diff /tmp/fcp-drill.source /tmp/fcp-drill.restored; then
  echo "FAILED: the restored copy differs from the backup snapshot (tables above)." >&2
  exit 1
fi
tables=$("${PG[@]}" sh -c 'wc -l < /tmp/fcp-drill.source')
rows=$("${PG[@]}" awk '{ total += $2 } END { print total }' /tmp/fcp-drill.source)
echo "    $tables tables, $rows rows: identical"

echo "4/4 The application's own checks on the restored copy"
for check in audit_verify ledger_integrity_check actuals_verify; do
  (cd backend && POSTGRES_DB="$SCRATCH" DB_ROLE=owner uv run python manage.py "$check" >/dev/null 2>&1) \
    || { echo "FAILED: $check on the restored copy." >&2; exit 1; }
  echo "    $check passed"
done

echo "Restore drill passed in $(( $(date +%s) - started )) s (backup $((backed_up - started)) s, restore $((restored - backed_up)) s)."
