#!/bin/sh
# The scheduled jobs of the platform on the owner's computer (V1-3), as the AWS schedules run them
# (infra/terraform/modules/app): every 5 minutes the alert emails, every 15 minutes the cash
# forecast and projection refresh, every night the integrity checks and workspace purges.
# Owner-role jobs get the schema-owner credentials through DB_ROLE=owner.
set -u
run() { echo "$(date -u +%FT%TZ) $*"; python manage.py "$@" || echo "$(date -u +%FT%TZ) FAILED: $*"; }
owner() { DB_ROLE=owner run "$@"; }
tick=0
night=""
while true; do
  run dashboards_send_alert_emails
  if [ $((tick % 3)) -eq 0 ]; then
    run cashflow_refresh
    run projections_refresh
  fi
  today="$(date -u +%F)"
  if [ "$(date -u +%H)" -ge 1 ] && [ "$night" != "$today" ]; then  # once a day, after 01:00 UTC
    owner audit_verify
    owner ledger_integrity_check
    owner actuals_verify
    owner tenancy_purge_workspaces
    night="$today"
  fi
  tick=$((tick + 1))
  sleep 300
done
