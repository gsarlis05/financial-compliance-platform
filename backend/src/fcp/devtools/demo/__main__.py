"""Command line: load the Milestone 1 demo workspace (``make demo``). Local development only.

Examples::

    python -m fcp.devtools.demo
    python -m fcp.devtools.demo --share-with you@example.com   # you can then open it in the UI

Each run creates a new "Demo Trading" workspace with one year of synthetic, monthly-summarised
books, and prints every step of the AC-G5 demo script.
"""

import argparse
import json
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fcp.devtools.demo", description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--share-with", metavar="EMAIL", help="existing user to invite")
    parser.add_argument("--share-role", default="finance_manager")
    parser.add_argument(
        "--json",
        metavar="PATH",
        help="also write the workspace, its year-end figures and the agreement checks (V1-4) "
        "to this file, for the browser walk-through",
    )
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
    if args.json:
        statements = {key: {r["code"]: r["current"] for r in result.statements[key]["rows"]
                            if r["current"] is not None}
                      for key in ("profit_and_loss", "balance_sheet", "cash_flow")}  # fmt: skip
        with open(args.json, "w", encoding="utf-8") as out:
            json.dump({"slug": result.slug, "entity_id": result.entity_id,
                       "bank_balance": result.bank_balance, "statements": statements,
                       "forecast_opening": result.forecast.get("opening_cash"),
                       "agreements": [{"name": a.name, "left": a.left, "right": a.right,
                                       "ok": a.ok} for a in result.agreements]},
                      out, indent=1)  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
