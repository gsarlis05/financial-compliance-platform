"""In-app alerts (M4-7, AC-GO4): raised on a change of state and not again while it holds;
acknowledged once; kept for good. Uses the goals fixture (tests/goals/test_goals.py): Q1 2026
actuals and an approved 2026 budget of 1,000 sales a month."""

from typing import Any

import pytest
from django.db import DatabaseError, transaction

from fcp.core.db.rls import set_context
from fcp.modules.dashboards.models import Alert, AlertState

from ..goals.test_goals import budget, evaluate, g, goal
from ..kpi.test_kpis import k
from ..ledger.conftest import books, join

pytestmark = pytest.mark.django_db
__all__ = ["books", "g", "k"]


def alerts(g: dict[str, Any], client: Any = None, **query: str) -> list[dict[str, Any]]:
    suffix = "?" + "&".join(f"{a}={b}" for a, b in query.items()) if query else ""
    found = (client or g["client"]).get(f"{g['base']}/alerts{suffix}")
    assert found.status_code == 200, found.content
    out: list[dict[str, Any]] = found.json()
    return out


def revise(g: dict[str, Any], goal_id: str, target: str) -> None:
    made = g["client"].post_json(
        f"{g['base']}/goals/{goal_id}/versions",
        {"target_type": "ABSOLUTE", "target": target, "reason": "test"},
    )
    assert made.status_code == 201, made.content


def test_goal_status_alert_is_raised_once_per_change(g: dict[str, Any]) -> None:
    budget(g)
    made = goal(g, "Revenue 12k", "REVENUE", "ABSOLUTE", "12000")  # 10,000 projected
    evaluate(g, made["id"])
    first = alerts(g)
    assert [(a["kind"], a["state"], a["severity"]) for a in first] == [
        ("GOAL_STATUS", "OFF_TRACK", "CRITICAL")
    ]
    assert first[0]["title"] == "Goal Revenue 12k is off track"
    assert first[0]["subject_id"] == made["id"]
    assert first[0]["detail"] == "Evaluated as of 2026-03-31; gap to target 2000.00"
    assert first[0]["source_run_id"] is not None
    evaluate(g, made["id"])  # unchanged: not raised again
    assert len(alerts(g)) == 1
    revise(g, made["id"], "9000")
    evaluate(g, made["id"])  # on track: no alert, the state is reset
    assert len(alerts(g)) == 1
    revise(g, made["id"], "10400")  # 10,000 misses by 4% of 10,400: at risk
    evaluate(g, made["id"])
    second = alerts(g)
    assert [(a["state"], a["severity"]) for a in second] == [
        ("AT_RISK", "WARNING"),
        ("OFF_TRACK", "CRITICAL"),
    ]
    counts = g["client"].get(f"{g['base']}/alerts/open-count").json()
    assert counts == {"warning": 1, "critical": 1}


def test_threshold_breach_alert(g: dict[str, Any]) -> None:
    made = goal(g, "Cash at least 2,350", "CASH", "MAINTAIN_MIN", "2350")
    evaluate(g, made["id"])
    found = {a["kind"]: a for a in alerts(g)}
    assert found["GOAL_STATUS"]["state"] == "AT_RISK"
    breach = found["GOAL_BREACH"]
    assert (breach["title"], breach["period"]) == (
        "Goal Cash at least 2,350: threshold breached",
        "2026-02-28",
    )
    evaluate(g, made["id"])
    assert len(alerts(g)) == 2
    margin = goal(g, "Margin 35%", "kpi:EBITDA_MARGIN", "ABSOLUTE", "0.35")
    evaluate(g, margin["id"])
    newest = alerts(g)[0]
    assert newest["title"] == "Goal Margin 35% is off track"
    assert newest["detail"].endswith("gap to target 5.00 percentage points")


def test_budget_overrun_and_trend_alerts(g: dict[str, Any]) -> None:
    budget(g)
    check = f"{g['base']}/alerts/check-budgets"
    # To April 2026: sales 1,000 against 4,000 (-75%), and February to April each below budget.
    done = g["client"].post_json(check, {"month": "2026-04-01"})
    assert done.json() == {"raised": 2}, done.content
    found = {a["kind"]: a for a in alerts(g)}
    overrun, trend = found["BUDGET_OVERRUN"], found["BUDGET_TREND"]
    assert overrun["title"] == "Plan 2026: REV.SALES unfavourable against budget year to date"
    assert "actual 1000.00, budget 4000.00, variance -3000.00 (-75.0%)" in overrun["detail"]
    assert trend["title"] == "Plan 2026: REV.SALES unfavourable 3 months in a row"
    assert g["client"].post_json(check, {"month": "2026-04-01"}).json() == {"raised": 0}
    # In March the trend is not complete (January met the budget), and the overrun holds.
    assert g["client"].post_json(check, {"month": "2026-03-01"}).json() == {"raised": 0}
    assert len(alerts(g)) == 2


def test_acknowledgement_is_final_and_alerts_are_kept(
    g: dict[str, Any], make_user: Any, api_client: Any
) -> None:
    made = goal(g, "Cash at least 2,350", "CASH", "MAINTAIN_MIN", "2350")
    evaluate(g, made["id"])
    viewer = join(g["client"], g["ws"]["slug"], make_user("ro@example.test"), api_client,
                  "read_only")  # fmt: skip
    holder = join(g["client"], g["ws"]["slug"], make_user("bh@example.test"), api_client,
                  "budget_holder")  # fmt: skip
    assert len(alerts(g, viewer)) == 2
    assert holder.get(f"{g['base']}/alerts").status_code == 403
    first = alerts(g)[0]
    url = f"{g['base']}/alerts/{first['id']}/acknowledge"
    assert viewer.post_json(url, {"note": "seen"}).status_code == 403
    done = g["client"].post_json(url, {"note": "Customer payment due on Friday"})
    assert done.status_code == 200, done.content
    assert done.json()["acknowledged_at"] is not None
    assert done.json()["acknowledgement_note"] == "Customer payment due on Friday"
    assert g["client"].post_json(url, {}).status_code == 409
    assert len(alerts(g)) == 1
    assert len(alerts(g, include_acknowledged="true")) == 2
    with transaction.atomic():
        set_context(tenant_id=g["ws"]["id"])
        with pytest.raises(DatabaseError, match="only be acknowledged"), transaction.atomic():
            Alert.objects.filter(id=first["id"]).update(title="changed")
        with pytest.raises(DatabaseError, match="kept"), transaction.atomic():
            Alert.objects.filter(id=first["id"]).delete()
        with pytest.raises(DatabaseError, match="kept"), transaction.atomic():
            AlertState.objects.all().delete()
