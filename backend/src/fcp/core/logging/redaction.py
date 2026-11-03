"""Log redaction (threat T20, CONTRIBUTING: logs carry identifiers only).

Two layers:
1. **Key allow-list.** Only known-safe keys keep their values; any other key's value is
   replaced with ``[REDACTED]``. Developers therefore cannot leak a field by adding it to a log
   call; they must add the key here, deliberately and in review.
2. **Pattern scrubbing.** String values of allowed keys (including the message and exception
   text) are scrubbed of e-mail addresses, IBANs, payment-card-like numbers, Cyprus TIN/VAT
   numbers and decimal amounts.
"""

import re
from collections.abc import Mapping, MutableMapping
from typing import Any

REDACTED = "[REDACTED]"

ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        # structlog / stdlib metadata
        "event",
        "level",
        "timestamp",
        "logger",
        "exception",
        "exc_info",
        "stack_info",
        # correlation and identity (opaque identifiers only)
        "correlation_id",
        "tenant_id",
        "entity_id",
        "user_id",
        "workspace_kind",
        # request metadata (no query string, no body, no headers)
        "method",
        "path",
        "status_code",
        "duration_ms",
        # error metadata
        "error_code",
        "error_type",
        # generic safe metrics
        "count",
        "module",
        "job",
        "attempt",
    }
)

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    # IBAN: country code, check digits, 11-30 alphanumerics (optionally space-grouped).
    (re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b"), "[IBAN]"),
    # Cyprus TIN / VAT: 8 digits followed by a letter, optionally prefixed with CY.
    (re.compile(r"\b(?:CY)?\d{8}[A-Z]\b"), "[TAX_ID]"),
    # Card-like or long identifiers: 12-19 digits, optionally separated by spaces or dashes.
    (re.compile(r"\b\d(?:[ -]?\d){11,18}\b"), "[NUMBER]"),
    # Decimal amounts such as 1234.56, 1,234.56 or 1.234,56.
    (re.compile(r"(?<![\w.,])\d{1,3}(?:[.,]\d{3})*[.,]\d{1,4}(?![\w.,])"), "[AMOUNT]"),
)


# UUIDs are opaque identifiers that must survive scrubbing; they are masked first so the
# number patterns cannot match their digit groups.
_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def scrub(text: str) -> str:
    """Replace sensitive-looking substrings in ``text`` (UUIDs are preserved)."""
    uuids: list[str] = []

    def _mask(match: re.Match[str]) -> str:
        uuids.append(match.group(0))
        return f"\x00{len(uuids) - 1}\x00"

    text = _UUID.sub(_mask, text)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)

    def _unmask(match: re.Match[str]) -> str:
        index = int(match.group(1))
        # Text that already contained this marker (not one of ours) is left as is.
        return uuids[index] if index < len(uuids) else match.group(0)

    return re.sub(r"\x00(\d+)\x00", _unmask, text)


def _scrub_value(value: Any) -> Any:
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, Mapping):
        return {k: _scrub_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub_value(v) for v in value]
    return value


def redact_event_dict(
    _logger: object, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor applying the allow-list and pattern scrubbing."""
    for key in list(event_dict):
        if key not in ALLOWED_KEYS:
            event_dict[key] = REDACTED
        else:
            event_dict[key] = _scrub_value(event_dict[key])
    return event_dict
