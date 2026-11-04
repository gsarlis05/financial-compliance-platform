"""Refresh out-of-date cash forecasts of every workspace (M3-8).

Run once per schedule (every 15 minutes) or continuously, with the runtime role:
``python manage.py cashflow_refresh [--loop] [--interval 900]``.
"""

import time
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from ...tracking import refresh_all


class Command(BaseCommand):
    help = "Re-run cash forecasts that are out of date (scheduled job)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--loop", action="store_true", help="Keep refreshing")
        parser.add_argument("--interval", type=int, default=900, help="Seconds between passes")

    def handle(self, *args: Any, **options: Any) -> None:
        while True:
            report = refresh_all()
            self.stdout.write(
                f"Refreshed {report.refreshed} forecast(s); {report.current} "
                f"current; {len(report.skipped)} skipped."
            )
            if not options["loop"]:
                return
            time.sleep(options["interval"])
