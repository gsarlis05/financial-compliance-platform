"""Re-run stale rolling forecasts of every workspace (M6-4; M6F-6).

One pass every 15 minutes (a material change re-runs at once; other postings wait for each
forecast's regular interval), run once per schedule or continuously, with the runtime role:
``python manage.py projections_refresh [--loop] [--interval 900]``.
"""

import time
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from ...rolling import refresh_all


class Command(BaseCommand):
    help = "Re-run rolling forecasts that are stale (scheduled job)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--loop", action="store_true", help="Keep refreshing")
        parser.add_argument("--interval", type=int, default=900, help="Seconds between passes")

    def handle(self, *args: Any, **options: Any) -> None:
        while True:
            report = refresh_all()
            self.stdout.write(
                f"Refreshed {report.refreshed} rolling forecast(s); {report.current} "
                f"current; {len(report.skipped)} skipped."
            )
            if not options["loop"]:
                return
            time.sleep(options["interval"])
