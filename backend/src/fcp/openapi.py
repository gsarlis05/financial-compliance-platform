"""Export the OpenAPI document (AC-G3): ``python -m fcp.openapi docs/api/openapi.json [--check]``.

The committed ``docs/api/openapi.json`` is the published contract; CI runs ``--check`` so it can
never drift from the code.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def render() -> str:
    from fcp.api import api  # noqa: PLC0415 - needs configured Django

    schema: dict[str, Any] = api.get_openapi_schema(path_prefix="/api/")
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fcp.openapi", description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--check", action="store_true", help="fail if the file is out of date")
    args = parser.parse_args(argv)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fcp.settings.dev")
    import django  # noqa: PLC0415

    django.setup()
    content = render()
    if args.check:
        current = args.path.read_text(encoding="utf-8") if args.path.exists() else ""
        if current != content:
            sys.stderr.write(f"{args.path} is out of date; run `make openapi`.\n")
            return 1
        return 0
    args.path.parent.mkdir(parents=True, exist_ok=True)
    args.path.write_text(content, encoding="utf-8")
    sys.stdout.write(f"Wrote {args.path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
