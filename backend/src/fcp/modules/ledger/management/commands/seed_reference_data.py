"""Re-seed reference data (the VAT code catalogue). Idempotent; run with the schema-owner role.

``DB_ROLE=owner python manage.py seed_reference_data``. Migrations already seed it; this command
repairs or refreshes it (for example after editing a catalogue JSON file in a release).
"""

from typing import Any

from django.core.management.base import BaseCommand

from ...models import VatCode
from ...vat import seed_catalogue


class Command(BaseCommand):
    help = "Seed or refresh reference data (VAT code catalogue)."

    def handle(self, *args: Any, **options: Any) -> None:
        count = seed_catalogue(VatCode)
        self.stdout.write(f"VAT code catalogue: {count} codes up to date.")
