"""Time-ordered UUIDv7 identifiers (RFC 9562), used as primary keys (docs/planning/03)."""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """Return a new UUIDv7: 48-bit Unix ms timestamp, version 7, RFC 4122 variant, random bits."""
    unix_ms = time.time_ns() // 1_000_000
    random_bits = int.from_bytes(os.urandom(10), "big")  # 80 bits; 74 are used
    value = (unix_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # version
    value |= ((random_bits >> 68) & 0xFFF) << 64  # rand_a: 12 bits
    value |= 0b10 << 62  # variant
    value |= random_bits & ((1 << 62) - 1)  # rand_b: 62 bits
    return uuid.UUID(int=value)
