"""Seed or refresh all reference data (idempotent). Run with the schema-owner role:
``DB_ROLE=owner python manage.py seed_reference_data``.

Migrations already seed reference data; this repairs or refreshes it, for example after a release
changes a catalogue file, or after a test run emptied the tables.
"""

from typing import Any

from django.core.management.base import BaseCommand

from fcp.core.db.reference import run_seeders


class Command(BaseCommand):
    help = "Seed or refresh reference data (VAT codes, financial taxonomy, ...)."

    def handle(self, *args: Any, **options: Any) -> None:
        for name, count in run_seeders().items():
            self.stdout.write(f"{name}: {count} rows up to date.")
