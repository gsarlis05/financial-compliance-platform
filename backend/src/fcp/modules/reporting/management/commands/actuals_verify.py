"""Verify the reporting.actuals read model against the ledger for every workspace (nightly).

``DB_ROLE=owner python manage.py actuals_verify``; exit code 1 when any workspace drifts. Fix a
drift with ``POST /api/w/{slug}/actuals/rebuild`` after investigating the cause.
"""

from typing import Any

import structlog
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from fcp.core.db.rls import set_context
from fcp.modules.tenancy.api import all_tenant_ids

from ...actuals import verify

log = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Verify the actuals read model against the ledger for every workspace."

    def handle(self, *args: Any, **options: Any) -> None:
        tenant_ids = all_tenant_ids()
        failed = 0
        for tenant_id in tenant_ids:
            with transaction.atomic():
                set_context(tenant_id=tenant_id)
                watermark, drifts = verify(tenant_id)
            if drifts:
                failed += 1
                log.error("reporting.actuals_drift", tenant_id=str(tenant_id), count=len(drifts),
                          error_code="reporting.actuals_drift")  # fmt: skip
                self.stderr.write(
                    f"DRIFT {tenant_id}: {len(drifts)} fact(s) differ (wm {watermark})"
                )
        self.stdout.write(f"Verified actuals for {len(tenant_ids)} workspace(s); {failed} drifted.")
        if failed:
            raise CommandError(f"{failed} workspace(s) have actuals that differ from the ledger")
