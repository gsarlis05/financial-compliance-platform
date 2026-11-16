"""Public interface of the ``dashboards`` module and its HTTP routes (M4-7: in-app alerts;
M4-8: the CFO dashboard and its saved layouts).

Routes are entity-scoped: ``/api/w/{slug}/entities/{entity_id}/...``.
"""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from django.http import HttpRequest
from ninja import Field, Query, Router, Schema

from fcp.core.api.permissions import requires
from fcp.modules.kpi.api import run_kpi_set
from fcp.modules.tenancy.api import workspace_ctx

from . import alerts as service
from . import layouts, overview, portfolio
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


# --- CFO dashboard (M4-8) ---------------------------------------------------------------------


class DashboardQuery(Schema):
    preset: Literal["MONTH", "QTD", "YTD"] = "YTD"
    month: date = Field(description="Any day of the month the period ends in")
    comparison: Literal["BUDGET", "PRIOR_YEAR"] = "BUDGET"


class DashboardPeriodOut(Schema):
    preset: str
    month: date
    date_from: date
    date_to: date
    fiscal_year_start: date
    comparison: str


class WidgetOut(Schema):
    type: str
    status: str = Field(description="ok, empty (with a reason) or denied (no permission)")
    reason: str
    options: dict[str, Any]
    data: dict[str, Any]


class DashboardOut(Schema):
    period: DashboardPeriodOut
    layout_source: str = Field(description="USER, WORKSPACE or BUILT_IN")
    widgets: list[WidgetOut]


def _period(ctx: Any, entity_id: UUID, q: DashboardQuery) -> overview.Period:
    return overview.period(ctx, entity_id, q.preset, q.month, q.comparison)


@router.get(f"{BASE}/dashboard", response=DashboardOut)
@requires("planning.read")
def dashboard(request: HttpRequest, slug: str, entity_id: UUID,
              q: Query[DashboardQuery]) -> DashboardOut:  # fmt: skip
    """Every widget of the user's layout for one period and comparison (AC-DB4)."""
    ctx = workspace_ctx(request, slug, entity_id)
    widgets, source = layouts.layout(ctx, entity_id)
    p = _period(ctx, entity_id, q)
    keys: list[str] = next((w.get("kpis", []) for w in widgets if w["type"] == "kpis"), [])
    built = overview.overview(ctx, entity_id, p, list(keys))
    return DashboardOut(
        period=DashboardPeriodOut(**p.__dict__),
        layout_source=source,
        widgets=[WidgetOut(type=w["type"], status=built[w["type"]].status,
                           reason=built[w["type"]].reason,
                           options={k: v for k, v in w.items() if k != "type"},
                           data=built[w["type"]].data) for w in widgets],
    )  # fmt: skip


class RefreshOut(Schema):
    kpi_sets: int
    alerts_raised: int


@router.post(f"{BASE}/dashboard/refresh", response=RefreshOut)
@requires("planning.run")
def refresh(request: HttpRequest, slug: str, entity_id: UUID,
            payload: DashboardQuery) -> RefreshOut:  # fmt: skip
    """Calculate the KPI sets the period needs and check the budgets for alerts."""
    ctx = workspace_ctx(request, slug, entity_id)
    p = _period(ctx, entity_id, payload)
    periods = [(p.date_from, p.date_to)]
    if p.comparison == "PRIOR_YEAR":
        periods.append(p.prior)
    for first, last in periods:
        run_kpi_set(ctx, entity_id, date_from=first, date_to=last)
    raised = service.check_budgets(ctx, entity_id, p.month)
    return RefreshOut(kpi_sets=len(periods), alerts_raised=raised)


class LayoutIO(Schema):
    widgets: list[dict[str, Any]]


class LayoutOut(LayoutIO):
    source: str


@router.get(f"{BASE}/dashboard-layout", response=LayoutOut)
@requires("planning.read")
def get_layout(request: HttpRequest, slug: str, entity_id: UUID) -> LayoutOut:
    ctx = workspace_ctx(request, slug, entity_id)
    widgets, source = layouts.layout(ctx, entity_id)
    return LayoutOut(widgets=widgets, source=source)


@router.put(f"{BASE}/dashboard-layout", response=LayoutOut)
@requires("planning.read")
def save_layout(request: HttpRequest, slug: str, entity_id: UUID,
                payload: LayoutIO) -> LayoutOut:  # fmt: skip
    """Your own layout: widget types in order, and for KPI cards the KPI keys."""
    ctx = workspace_ctx(request, slug, entity_id)
    return LayoutOut(widgets=layouts.save(ctx, entity_id, payload.widgets), source="USER")


@router.delete(f"{BASE}/dashboard-layout", response=LayoutOut)
@requires("planning.read")
def reset_layout(request: HttpRequest, slug: str, entity_id: UUID) -> LayoutOut:
    ctx = workspace_ctx(request, slug, entity_id)
    layouts.reset(ctx, entity_id)
    widgets, source = layouts.layout(ctx, entity_id)
    return LayoutOut(widgets=widgets, source=source)


@router.put(f"{BASE}/dashboard-layout/default", response=LayoutOut)
@requires("dashboard.manage_default")
def save_default_layout(request: HttpRequest, slug: str, entity_id: UUID,
                        payload: LayoutIO) -> LayoutOut:  # fmt: skip
    """The layout everyone starts from until they save their own."""
    ctx = workspace_ctx(request, slug, entity_id)
    saved = layouts.save(ctx, entity_id, payload.widgets, default=True)
    return LayoutOut(widgets=saved, source="WORKSPACE")


# --- firm portfolio (M4-9) --------------------------------------------------------------------


class PortfolioQuery(Schema):
    month: date = Field(description="Any day of the month the year to date ends in")


class PortfolioPartOut(Schema):
    status: str = Field(description="ok, empty (with a reason) or denied")
    reason: str
    data: dict[str, Any]


class PortfolioRowOut(Schema):
    entity_id: UUID
    legal_name: str
    entity_type: str
    cash: PortfolioPartOut
    kpis: PortfolioPartOut
    goals: PortfolioPartOut
    alerts: PortfolioPartOut


@router.get("/w/{slug}/portfolio", response=list[PortfolioRowOut])
@requires("planning.read")
def firm_portfolio(request: HttpRequest, slug: str,
                   q: Query[PortfolioQuery]) -> list[PortfolioRowOut]:  # fmt: skip
    """One row per client entity you may see (AC-DB6), computed now under your permissions."""
    ctx = workspace_ctx(request, slug)
    rows = portfolio.portfolio(ctx, q.month)
    return [
        PortfolioRowOut(
            entity_id=r["entity"].id, legal_name=r["entity"].legal_name,
            entity_type=r["entity"].entity_type,
            **{k: PortfolioPartOut(status=w.status, reason=w.reason, data=w.data)
               for k, w in r["parts"].items()},
        )
        for r in rows
    ]  # fmt: skip
