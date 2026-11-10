"""The firm portfolio (M4-9, doc 10 §10, AC-DB6).

A summary row per client entity in the firm's own workspace that the user may see with
``planning.read`` (entity-scoped roles see only their clients). Each row is computed on request,
entity by entity, under the user's own permissions: no cross-tenant query, and nothing is stored,
so a revoked role removes the client on the next request and leaves no derived metrics behind.
Engagement grants to client-owned workspaces join in M5-4.

Per client:
- cash: the latest 13-week forecast's opening and first shortfall, and whether it is out of date;
- KPIs: gross margin, current ratio and DSO from the latest year-to-date KPI set, if any;
- goals: how many are on track, at risk, off track or not evaluated;
- alerts: open critical and warning alerts.
"""

from collections import Counter
from datetime import date
from typing import Any
from uuid import UUID

from fcp.modules.tenancy.api import WorkspaceContext, permitted_entities

from .overview import Widget, _alerts, _cash, _goals, _guard, _kpis, period

READ = "planning.read"
PORTFOLIO_KPIS = ["GROSS_MARGIN", "CURRENT_RATIO", "DSO"]
GOAL_STATES = ("ON_TRACK", "AT_RISK", "OFF_TRACK", "UNDETERMINED", "NOT_EVALUATED")


def _summary(ctx: WorkspaceContext, entity_id: UUID, month: date) -> dict[str, Widget]:
    p = period(ctx, entity_id, "YTD", month, "BUDGET")
    goals = _guard(lambda: _goals(ctx, entity_id), "No goals yet.")
    if goals.status == "ok":
        counts = Counter(g["status"] or "NOT_EVALUATED" for g in goals.data["goals"])
        goals = Widget(data={k: counts.get(k, 0) for k in GOAL_STATES})
    cash = _guard(lambda: _cash(ctx, entity_id), "No cash forecast yet.")
    if cash.status == "ok":
        cash = Widget(data={k: cash.data[k] for k in ("as_of", "stale", "opening",
                                                       "first_shortfall")})  # fmt: skip
    return {
        "cash": cash,
        "kpis": _guard(lambda: _kpis(ctx, entity_id, p, PORTFOLIO_KPIS),
                       "No KPI set for the year to date yet."),
        "goals": goals,
        "alerts": _guard(lambda: {k: v for k, v in _alerts(ctx, entity_id).items()
                                  if k != "latest"}, "No alerts."),
    }  # fmt: skip


def portfolio(ctx: WorkspaceContext, month: date) -> list[dict[str, Any]]:
    return [
        {"entity": e, "parts": _summary(ctx, e.id, month)} for e in permitted_entities(ctx, READ)
    ]
