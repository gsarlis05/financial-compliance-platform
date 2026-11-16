"""Create the local documents bucket (development only; deployed buckets come from IaC)."""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ...storage import ensure_bucket


class Command(BaseCommand):
    help = "Create the local document bucket in the development object store (DEBUG only)."

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("Only for local development: deployed buckets are created by IaC.")
        ensure_bucket()
        self.stdout.write(f"Bucket {settings.DOCUMENTS_BUCKET} is ready.")
