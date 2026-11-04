"""Canonical hashing of calculation inputs and outputs (M3-2, doc 10 P4).

The same value always gives the same bytes:
- dictionary keys are sorted;
- a Decimal is written without trailing zeros (``1.50`` and ``1.5`` are the same number);
- dates are written as ISO dates, UUIDs as lowercase strings and enums as their value.

Floats are refused: calculation code never uses them.
"""

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Context, Decimal
from enum import Enum
from uuid import UUID


def canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("only finite decimals can be hashed")
    if value.is_zero():
        return "0"
    # A context as wide as the number, so normalising only drops trailing zeros (never rounds).
    return format(value.normalize(Context(prec=len(value.as_tuple().digits))), "f")


def _plain(value: object) -> object:  # noqa: PLR0911 (one branch per type)
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):  # fcp-lint: allow-float (refusing floats, not using them)
        raise TypeError("floats are not allowed in calculation inputs or outputs")
    if isinstance(value, Decimal):
        return {"$d": canonical_decimal(value)}
    if isinstance(value, Enum):
        return _plain(value.value)
    if isinstance(value, datetime):
        raise TypeError("calculations use dates, not datetimes")
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    raise TypeError(f"cannot hash a {type(value).__name__}")


def canonical(value: object) -> bytes:
    return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode()  # fmt: skip


def digest(value: object) -> str:
    """SHA-256 (hex) of the canonical form."""
    return hashlib.sha256(canonical(value)).hexdigest()


def jsonable(value: object) -> object:
    """The canonical form as JSON-compatible data (for storing inputs)."""
    return _plain(value)
