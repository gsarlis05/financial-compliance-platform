"""HTTP routes for the audit trail (mounted by ``fcp.api``)."""

from datetime import datetime
from uuid import UUID

from django.http import HttpRequest
from ninja import Field, Query, Router, Schema

from fcp.core.api.permissions import requires
from fcp.modules.tenancy.api import workspace_ctx

from .chain import verify
from .models import AuditEvent

router = Router(tags=["audit"])


class AuditEventOut(Schema):
    seq: int
    occurred_at: datetime
    actor_user_id: UUID | None
    actor_type: str
    action: str
    subject_type: str
    subject_id: str
    entity_id: UUID | None
    changes: dict[str, object]
    correlation_id: str
    hash: str


class AuditFilter(Schema):
    subject_type: str | None = None
    subject_id: str | None = None
    after_seq: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)


class ChainStatusOut(Schema):
    ok: bool
    events: int
    broken_at_seq: int | None
    reason: str


@router.get("/w/{slug}/audit-events", response=list[AuditEventOut])
@requires("audit.read")
def list_events(
    request: HttpRequest, slug: str, filters: Query[AuditFilter]
) -> list[AuditEventOut]:
    ctx = workspace_ctx(request, slug)
    queryset = AuditEvent.objects.filter(tenant_id=ctx.tenant.id, seq__gt=filters.after_seq)
    if filters.subject_type:
        queryset = queryset.filter(subject_type=filters.subject_type)
    if filters.subject_id:
        queryset = queryset.filter(subject_id=filters.subject_id)
    return [
        AuditEventOut(
            seq=e.seq,
            occurred_at=e.occurred_at,
            actor_user_id=e.actor_user_id,
            actor_type=e.actor_type,
            action=e.action,
            subject_type=e.subject_type,
            subject_id=e.subject_id,
            entity_id=e.entity_id,
            changes=e.changes,
            correlation_id=e.correlation_id,
            hash=bytes(e.hash).hex(),
        )
        for e in queryset.order_by("seq")[: filters.limit]
    ]


@router.get("/w/{slug}/audit-events/verify", response=ChainStatusOut)
@requires("audit.read")
def verify_chain(request: HttpRequest, slug: str) -> ChainStatusOut:
    status = verify(workspace_ctx(request, slug).tenant.id)
    return ChainStatusOut(
        ok=status.ok, events=status.events, broken_at_seq=status.broken_at_seq, reason=status.reason
    )
