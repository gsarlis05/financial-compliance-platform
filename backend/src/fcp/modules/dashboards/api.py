"""Public interface of the ``dashboards`` module and its HTTP routes (M4-7: in-app alerts).

Routes are entity-scoped: ``/api/w/{slug}/entities/{entity_id}/...``.
"""

from datetime import date, datetime
from uuid import UUID

from django.http import HttpRequest
from ninja import Field, Query, Router, Schema

from fcp.core.api.permissions import requires
from fcp.modules.tenancy.api import workspace_ctx

from . import alerts as service
from .models import Alert

__all__ = ["Alert", "router"]

router = Router(tags=["dashboards"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"


class AlertOut(Schema):
    id: UUID
    key: str = Field(description="What is watched; an alert is raised once per change of state")
    kind: str
    state: str
    severity: str
    title: str
    detail: str
    subject_type: str = Field(description="goal or budget")
    subject_id: UUID
    period: date | None
    source_run_id: UUID | None = Field(description="The calculation run behind it, if any")
    created_at: datetime
    acknowledged_by_name: str
    acknowledged_at: datetime | None
    acknowledgement_note: str


def _out(a: Alert) -> AlertOut:
    by = a.acknowledged_by
    return AlertOut(
        id=a.id, key=a.key, kind=a.kind, state=a.state, severity=a.severity, title=a.title,
        detail=a.detail, subject_type=a.subject_type, subject_id=a.subject_id, period=a.period,
        source_run_id=a.source_run_id, created_at=a.created_at,
        acknowledged_by_name=(by.display_name or by.email) if by else "",
        acknowledged_at=a.acknowledged_at, acknowledgement_note=a.acknowledgement_note,
    )  # fmt: skip


class AlertsQuery(Schema):
    include_acknowledged: bool = False
    limit: int = Field(100, ge=1, le=500)


@router.get(f"{BASE}/alerts", response=list[AlertOut])
@requires("planning.read")
def list_alerts(request: HttpRequest, slug: str, entity_id: UUID,
                q: Query[AlertsQuery]) -> list[AlertOut]:  # fmt: skip
    """Newest first; only alerts whose source you may see (goals, budgets)."""
    ctx = workspace_ctx(request, slug, entity_id)
    found = service.alerts(ctx, entity_id, include_acknowledged=q.include_acknowledged,
                           limit=q.limit)  # fmt: skip
    return [_out(a) for a in found]


class AlertCountsOut(Schema):
    warning: int
    critical: int


@router.get(f"{BASE}/alerts/open-count", response=AlertCountsOut)
@requires("planning.read")
def open_count(request: HttpRequest, slug: str, entity_id: UUID) -> AlertCountsOut:
    ctx = workspace_ctx(request, slug, entity_id)
    counts = service.open_counts(ctx, entity_id)
    return AlertCountsOut(warning=counts["WARNING"], critical=counts["CRITICAL"])


class AlertCheckIn(Schema):
    month: date | None = Field(None, description="Default: the last complete month")


class AlertCheckOut(Schema):
    raised: int


@router.post(f"{BASE}/alerts/check-budgets", response=AlertCheckOut)
@requires("planning.read")
def check_budgets(request: HttpRequest, slug: str, entity_id: UUID,
                  payload: AlertCheckIn) -> AlertCheckOut:  # fmt: skip
    """Check the current approved budgets for overruns and 3-month unfavourable trends (needs
    ``budget.read``; otherwise nothing is checked). Goal alerts come with each evaluation."""
    ctx = workspace_ctx(request, slug, entity_id)
    return AlertCheckOut(raised=service.check_budgets(ctx, entity_id, payload.month))


class AcknowledgeIn(Schema):
    note: str = Field("", max_length=300)


@router.post(f"{BASE}/alerts/{{uuid:alert_id}}/acknowledge", response=AlertOut)
@requires("alert.acknowledge")
def acknowledge(request: HttpRequest, slug: str, entity_id: UUID, alert_id: UUID,
                payload: AcknowledgeIn) -> AlertOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return _out(service.acknowledge(ctx, entity_id, alert_id, payload.note))
