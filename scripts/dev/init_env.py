"""Create .env from .env.example, replacing each placeholder with a fresh random secret.

Never overwrites an existing .env. Local development only.
"""

import os
import secrets
import sys
from pathlib import Path

PLACEHOLDER = "generated-by-make-dev-env"
ROOT = Path(__file__).resolve().parents[2]


def _append_missing(target: Path) -> int:
    """Add variables introduced since .env was created; existing values are never changed."""
    existing = {
        line.split("=", 1)[0]
        for line in target.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.startswith("#")
    }
    added = []
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.startswith("#") and key not in existing:
            added.append(f"{key}={secrets.token_urlsafe(32) if value == PLACEHOLDER else value}")
    if added:
        with target.open("a", encoding="utf-8") as f:
            f.write("\n".join(added) + "\n")
        print(f"Added {len(added)} new variable(s) to .env: {', '.join(a.split('=')[0] for a in added)}")
    else:
        print(".env is up to date.")
    return 0


def main() -> int:
    target = ROOT / ".env"
    if target.exists():
        return _append_missing(target)
    lines = []
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines(keepends=True):
        key, sep, value = line.partition("=")
        if sep and value.strip() == PLACEHOLDER:
            line = f"{key}={secrets.token_urlsafe(32)}\n"
        lines.append(line)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print("Created .env with random local secrets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
