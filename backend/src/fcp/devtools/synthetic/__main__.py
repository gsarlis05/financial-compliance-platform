"""Command line: generate synthetic datasets.

Examples::

    python -m fcp.devtools.synthetic business --seed 42 --out ../var/synthetic/business
    python -m fcp.devtools.synthetic household --seed 7 --out ../var/synthetic/household
    python -m fcp.devtools.synthetic business --profile ../var/my-business-profile.json \\
        --out ../var/synthetic/my-business
    python -m fcp.devtools.synthetic business --print-profile > ../var/my-business-profile.json

Use ``--print-profile`` to get the default profile as a starting point, adjust the levels to
resemble your situation, and keep the file in the git-ignored ``var/`` directory.
"""

import argparse
import json
import sys
from pathlib import Path

from . import generate_business, generate_household
from .profiles import (
    BusinessProfile,
    HouseholdProfile,
    load_business_profile,
    load_household_profile,
    profile_to_json,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fcp.devtools.synthetic", description=__doc__)
    parser.add_argument("kind", choices=["business", "household"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--profile", type=Path, help="JSON profile (defaults to the demo preset)")
    parser.add_argument("--out", type=Path, help="output directory")
    parser.add_argument("--print-profile", action="store_true", help="print the profile and exit")
    args = parser.parse_args(argv)

    if args.kind == "business":
        business = load_business_profile(args.profile) if args.profile else BusinessProfile()
        profile_json = profile_to_json(business)
    else:
        household = load_household_profile(args.profile) if args.profile else HouseholdProfile()
        profile_json = profile_to_json(household)

    if args.print_profile:
        sys.stdout.write(json.dumps(profile_json, indent=2, sort_keys=True) + "\n")
        return 0
    if args.out is None:
        parser.error("--out is required unless --print-profile is given")

    dataset = (
        generate_business(business, args.seed)
        if args.kind == "business"
        else generate_household(household, args.seed)
    )
    written = dataset.write(args.out)
    sys.stdout.write(
        f"Wrote {len(written)} files to {args.out} (fingerprint {dataset.fingerprint()[:16]}).\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
