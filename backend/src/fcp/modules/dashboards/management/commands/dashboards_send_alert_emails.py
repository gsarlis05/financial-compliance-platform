"""Send alert emails and daily digests (M8-5).

One pass every 5 minutes, run once per schedule or continuously, with the runtime role:
``python manage.py dashboards_send_alert_emails [--loop] [--interval 300]``.
"""

import time
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from ...emails import send_all


class Command(BaseCommand):
    help = "Send due alert emails and daily digests (scheduled job)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--loop", action="store_true", help="Keep sending")
        parser.add_argument("--interval", type=int, default=300, help="Seconds between passes")

    def handle(self, *args: Any, **options: Any) -> None:
        while True:
            r = send_all()
            self.stdout.write(
                f"Sent {r.sent}; {r.retrying} to retry; {r.failed} failed; "
                f"{r.skipped} over the hourly limit; {r.digests} digest(s) prepared."
            )
            if not options["loop"]:
                return
            time.sleep(options["interval"])
