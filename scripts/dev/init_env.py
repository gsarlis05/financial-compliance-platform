"""Create .env from .env.example, replacing each placeholder with a fresh random secret.

Never overwrites an existing .env. Local development only.
"""

import os
import secrets
import sys
from pathlib import Path

PLACEHOLDER = "generated-by-make-dev-env"
ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    target = ROOT / ".env"
    if target.exists():
        print(".env already exists; leaving it unchanged.")
        return 0
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
