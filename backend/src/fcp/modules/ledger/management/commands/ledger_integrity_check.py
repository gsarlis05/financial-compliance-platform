"""Run the ledger integrity checks for every workspace. Exit code 1 if any workspace fails.

Schedule nightly with the schema-owner role (``make ops-checks``):
``DB_ROLE=owner python manage.py ledger_integrity_check``.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from fcp.modules.tenancy.api import all_tenant_ids

from ...integrity import run_checks
from ...models import IntegrityCheckRun


class Command(BaseCommand):
    help = "Run ledger integrity checks for every workspace."

    def handle(self, *args: Any, **options: Any) -> None:
        tenant_ids = all_tenant_ids()
        failed = 0
        for tenant_id in tenant_ids:
            run = run_checks(tenant_id)
            if run.status == IntegrityCheckRun.Status.FAILED:
                failed += 1
                broken = ", ".join(r["check"] for r in run.results if not r["ok"])
                self.stderr.write(f"FAILED {tenant_id}: {broken}")
        self.stdout.write(f"Checked {len(tenant_ids)} workspace(s); {failed} failed.")
        if failed:
            raise CommandError(f"{failed} workspace(s) failed the ledger integrity checks")
