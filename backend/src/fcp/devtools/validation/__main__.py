"""``python -m fcp.devtools.validation [--check]``: see ``harness``."""

import os
import sys


def main() -> int:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fcp.settings.dev")
    import django  # noqa: PLC0415 - Django must be configured first

    django.setup()
    from .harness import main as run  # noqa: PLC0415

    return run()


if __name__ == "__main__":
    sys.exit(main())
