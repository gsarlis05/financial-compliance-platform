"""Purge workspaces whose deletion was confirmed and whose grace period has ended (M5-6).

Run with the schema-owner role: ``DB_ROLE=owner python manage.py tenancy_purge_workspaces``.
Exit code 1 if a purge fails; the others still run.
"""

from typing import Any

import structlog
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ... import lifecycle

log = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Delete every row and file of workspaces whose confirmed deletion is due."

    def handle(self, *args: Any, **options: Any) -> None:
        if settings.DB_ROLE != "owner":
            raise CommandError("Run with DB_ROLE=owner: the purge needs the schema-owner role.")
        failed = 0
        rows = lifecycle.due()
        for row in rows:
            try:
                counts = lifecycle.purge(row)
            except Exception as error:  # noqa: BLE001 - one failure must not stop the others
                failed += 1
                log.error(
                    "tenancy.purge_failed",
                    tenant_id=str(row.tenant_id),
                    error_code="tenancy.purge_failed",
                    reason=type(error).__name__,
                )
                self.stderr.write(f"FAILED {row.tenant_id}: {error}")
                continue
            log.info("tenancy.workspace_purged", tenant_id=str(row.tenant_id),
                     rows=sum(counts.values()), tables=len(counts))  # fmt: skip
            self.stdout.write(f"Purged {row.tenant_id}: {sum(counts.values())} rows.")
        self.stdout.write(f"{len(rows) - failed} workspace(s) purged; {failed} failed.")
        if failed:
            raise CommandError(f"{failed} purge(s) failed")
