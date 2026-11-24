"""Idempotency keys for create and post operations (doc 05 §2, AC-C5).

A retried request with the same ``Idempotency-Key`` returns the original result instead of
acting twice; reusing a key for a different request is rejected.
"""

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any

from django.http import HttpRequest

from fcp.core.errors import ValidationFailedError
from fcp.modules.tenancy.api import WorkspaceContext

from .errors import IdempotencyConflictError
from .models import IdempotencyRecord

_KEY = re.compile(r"^[A-Za-z0-9_.:-]{8,100}$")


def run(
    ctx: WorkspaceContext,
    request: HttpRequest,
    operation: str,
    payload: Any,
    action: Callable[[], tuple[int, dict[str, Any]]],
) -> tuple[int, dict[str, Any]]:
    key = request.headers.get("Idempotency-Key")
    if key is None:
        return action()
    if not _KEY.match(key):
        raise ValidationFailedError(
            "Idempotency-Key must be 8-100 characters of letters, digits, '_', '.', ':' or '-'.",
            field_errors={"Idempotency-Key": ["invalid"]},
        )
    request_hash = hashlib.sha256(
        (operation + json.dumps(payload, sort_keys=True, default=str)).encode()
    ).hexdigest()
    existing = IdempotencyRecord.objects.filter(tenant=ctx.tenant, key=key).first()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise IdempotencyConflictError(
                "This Idempotency-Key was already used for a different request."
            )
        return existing.status_code, existing.response
    status, body = action()
    IdempotencyRecord.objects.create(
        tenant=ctx.tenant,
        key=key,
        operation=operation,
        request_hash=request_hash,
        response=body,
        status_code=status,
    )
    return status, body
