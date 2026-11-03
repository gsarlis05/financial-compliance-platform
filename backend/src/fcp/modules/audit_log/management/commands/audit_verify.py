"""Verify the audit hash chain of every workspace. Exit code 1 if any chain is broken.

Run with the schema-owner role: ``DB_ROLE=owner python manage.py audit_verify``.
"""

from typing import Any

import structlog
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from fcp.core.db.rls import set_context
from fcp.modules.tenancy.api import all_tenant_ids

from ...chain import verify

log = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Verify the audit hash chain of every workspace."

    def handle(self, *args: Any, **options: Any) -> None:
        broken = 0
        tenant_ids = all_tenant_ids()
        for tenant_id in tenant_ids:
            with transaction.atomic():
                set_context(tenant_id=tenant_id)
                status = verify(tenant_id)
            if not status.ok:
                broken += 1
                log.error("audit.chain_broken", tenant_id=str(tenant_id), count=status.events,
                          error_code="audit.chain_broken")  # fmt: skip
                self.stderr.write(
                    f"BROKEN {tenant_id}: seq {status.broken_at_seq}: {status.reason}"
                )
        self.stdout.write(f"Verified {len(tenant_ids)} workspace(s); {broken} broken.")
        if broken:
            raise CommandError(f"{broken} audit chain(s) broken")
