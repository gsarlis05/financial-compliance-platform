"""Process pending bank statement imports of every workspace (ADR-0015).

Run continuously as a worker (``--loop``), or once per schedule (default), with the runtime role:
``python manage.py banking_process_imports [--loop] [--interval 5]``.
"""

import time
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from ...services import process_pending


class Command(BaseCommand):
    help = "Parse pending bank statement imports (worker)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--loop", action="store_true", help="Keep polling for new imports")
        parser.add_argument("--interval", type=int, default=5, help="Seconds between polls")

    def handle(self, *args: Any, **options: Any) -> None:
        while True:
            done = process_pending()
            self.stdout.write(f"Processed {done} import(s).")
            if not options["loop"]:
                return
            time.sleep(options["interval"])
