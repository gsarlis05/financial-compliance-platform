"""Recording and verifying the audit hash chain."""

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from django.db import connection, transaction
from django.utils import timezone

from .models import AuditChainHead, AuditEvent

GENESIS_HASH = bytes(32)


def _default(value: object) -> object:
    if isinstance(value, Decimal | UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Audit values must be JSON-serialisable, got {type(value).__name__}")


def canonical_json(value: object) -> str:
    return json.dumps(
        value, default=_default, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def digest(value: object) -> str:
    """One-way digest for sensitive values (e.g. e-mail addresses): comparable, not readable."""
    return "sha256:" + hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _payload(event: AuditEvent) -> dict[str, Any]:
    return {
        "tenant_id": str(event.tenant_id),
        "seq": event.seq,
        "occurred_at": event.occurred_at.astimezone(UTC).isoformat(),
        "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
        "actor_type": event.actor_type,
        "action": event.action,
        "subject_type": event.subject_type,
        "subject_id": event.subject_id,
        "entity_id": str(event.entity_id) if event.entity_id else None,
        "changes": event.changes,
        "correlation_id": event.correlation_id,
    }


def compute_hash(prev_hash: bytes, event: AuditEvent) -> bytes:
    return hashlib.sha256(bytes(prev_hash) + canonical_json(_payload(event)).encode()).digest()


def record(  # noqa: PLR0913 - keyword-only; mirrors the audit event's fields
    *,
    tenant_id: UUID,
    action: str,
    subject_type: str,
    subject_id: object,
    actor_user_id: UUID | None,
    changes: Mapping[str, object] | None = None,
    sensitive: Iterable[str] = (),
    entity_id: UUID | None = None,
) -> AuditEvent:
    """Append an event in the caller's transaction (the RLS context must be that tenant).

    Keys listed in ``sensitive`` are stored as digests only (AC-D3). If the surrounding
    transaction rolls back, the event disappears with the change it describes (AC-D1).
    """
    if not connection.in_atomic_block:
        raise RuntimeError("Audit events must be written inside the transaction of the change.")
    sensitive_keys = set(sensitive)
    stored = {
        key: digest(value) if key in sensitive_keys and value is not None else value
        for key, value in (changes or {}).items()
    }
    normalised: dict[str, Any] = json.loads(canonical_json(stored))
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO audit_log_chain_head (tenant_id, last_seq, last_hash) VALUES (%s, 0, %s) "
            "ON CONFLICT (tenant_id) DO NOTHING",
            [tenant_id, GENESIS_HASH],
        )
    head = AuditChainHead.objects.select_for_update().get(tenant_id=tenant_id)
    event = AuditEvent(
        tenant_id=tenant_id,
        seq=head.last_seq + 1,
        occurred_at=timezone.now(),
        actor_user_id=actor_user_id,
        actor_type=AuditEvent.ActorType.USER if actor_user_id else AuditEvent.ActorType.SYSTEM,
        action=action,
        subject_type=subject_type,
        subject_id=str(subject_id),
        entity_id=entity_id,
        changes=normalised,
        correlation_id=str(structlog.contextvars.get_contextvars().get("correlation_id") or ""),
        prev_hash=bytes(head.last_hash),
    )
    event.hash = compute_hash(bytes(head.last_hash), event)
    event.save(force_insert=True)
    AuditChainHead.objects.filter(tenant_id=tenant_id).update(
        last_seq=event.seq, last_hash=event.hash
    )
    return event


@dataclass(frozen=True)
class ChainStatus:
    ok: bool
    events: int
    broken_at_seq: int | None = None
    reason: str = ""


def verify(tenant_id: UUID) -> ChainStatus:
    """Recompute the whole chain for a tenant (the RLS context must be that tenant)."""
    with transaction.atomic():
        prev = GENESIS_HASH
        expected_seq = 1
        count = 0
        for event in AuditEvent.objects.filter(tenant_id=tenant_id).order_by("seq").iterator():
            count += 1
            if event.seq != expected_seq:
                return ChainStatus(False, count, event.seq, f"gap: expected seq {expected_seq}")
            if bytes(event.prev_hash) != prev:
                return ChainStatus(False, count, event.seq, "previous-hash link broken")
            if compute_hash(prev, event) != bytes(event.hash):
                return ChainStatus(False, count, event.seq, "event content altered")
            prev = bytes(event.hash)
            expected_seq += 1
        head = AuditChainHead.objects.filter(tenant_id=tenant_id).first()
        if head is not None and (head.last_seq != count or bytes(head.last_hash) != prev):
            return ChainStatus(False, count, head.last_seq, "chain head does not match events")
        if head is None and count:
            return ChainStatus(False, count, None, "chain head missing")
    return ChainStatus(True, count)
