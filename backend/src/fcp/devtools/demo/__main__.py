"""Command line: load the Milestone 1 demo workspace (``make demo``). Local development only.

Examples::

    python -m fcp.devtools.demo
    python -m fcp.devtools.demo --share-with you@example.com   # you can then open it in the UI

Each run creates a new "Demo Trading" workspace with one year of synthetic, monthly-summarised
books, and prints every step of the AC-G5 demo script.
"""

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fcp.devtools.demo", description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--share-with", metavar="EMAIL", help="existing user to invite")
    parser.add_argument("--share-role", default="finance_manager")
    args = parser.parse_args(argv)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fcp.settings.dev")
    import django  # noqa: PLC0415 - Django must be configured first

    django.setup()
    from django.conf import settings  # noqa: PLC0415

    if not settings.DEBUG:
        sys.stderr.write("Refusing to load demo data: only allowed with DEBUG (local dev).\n")
        return 2
    from .walkthrough import run  # noqa: PLC0415

    result = run(
        seed=args.seed, share_with=args.share_with, share_role=args.share_role, host="localhost"
    )
    sys.stdout.write(
        f"\nDemo workspace: {result.slug}  (open http://localhost:5173/w/{result.slug})\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
