"""Goals against scenarios (M7-5, AC-GS1): a goal evaluated against shared scenarios uses each
scenario's figures, says so, is shown next to its base, and never changes; nothing is stored.

The plan: sales 1,000 a month in 2027, no actuals, no budget and no published projection, so the
base can only use the run rate (no actuals: nothing). The goal: revenue of 12,000 in 2027."""

from collections.abc import Callable
from typing import Any

import pytest

from fcp.modules.goals.models import Goal, GoalEvaluation

from ..ledger.conftest import books, join
from .test_runs_api import plan, scenario

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books", "plan"]


def shared(p: dict[str, Any], name: str, percent: str) -> str:
    url = scenario(p, ("PCT_CHANGE", {"driver": "revenue", "percent": percent}))
    p["client"].patch_json(url, {"name": name})
    assert p["client"].post_json(f"{url}/share", {}).status_code == 200
    return url.rsplit("/", 1)[1]


def test_goal_against_scenarios(plan: dict[str, Any], make_user: Make, api_client: Make) -> None:
    c, base = plan["client"], plan["base"]
    made = c.post_json(f"{base}/goals", {
        "name": "Revenue 2027", "metric": "REVENUE", "target_type": "ABSOLUTE", "target": "12000",
        "period_start": "2027-01-01", "period_end": "2027-12-31"})  # fmt: skip
    assert made.status_code == 201, made.content
    goal_id = made.json()["id"]
    up = shared(plan, "Growth +20%", "20")  # 12 x 1,200 = 14,400: on track, 2,400 above
    down = shared(plan, "Halved", "-50")  # 12 x 500 = 6,000: off track, 6,000 short
    url = f"{base}/goals/{goal_id}/scenario-outlooks"
    got = c.get(f"{url}?scenario_ids={up},{down}")
    assert got.status_code == 200, got.content
    rows = {r["label"]: r for r in got.json()}
    assert list(rows) == ["Base", "Growth +20%", "Halved"]
    assert (rows["Base"]["method"], rows["Base"]["projected"]) == ("RUN_RATE", "0")
    assert rows["Base"]["status"] == "OFF_TRACK"
    growth = rows["Growth +20%"]
    assert (growth["method"], growth["nature"], growth["status"]) == (
        "SCENARIO",
        "HYPOTHETICAL",
        "ON_TRACK",
    )
    assert (growth["projected"], growth["gap"]) == ("14400", "-2400")
    assert "then the scenario (hypothetical)" in growth["note"]
    halved = rows["Halved"]
    assert (halved["projected"], halved["gap"], halved["status"]) == ("6000", "6000", "OFF_TRACK")

    # Nothing is stored and the goal is unchanged; no alerts follow.
    assert GoalEvaluation.objects.filter(goal_id=goal_id).count() == 0
    goal = Goal.objects.get(id=goal_id)
    assert goal.status == Goal.Status.ACTIVE
    # The goal's own evaluation still uses the base, not a scenario.
    own = c.post_json(f"{base}/goals/{goal_id}/evaluations", {}).json()
    assert own["method"] == "RUN_RATE"

    # Refusals: more than three, a draft scenario, a cash goal, a read-only user.
    many = ",".join([up, down, up])
    assert c.get(f"{url}?scenario_ids={many}").status_code == 422
    draft = scenario(plan).rsplit("/", 1)[1]
    assert c.get(f"{url}?scenario_ids={draft}").status_code == 409
    assert c.get(f"{url}?scenario_ids=not-an-id").status_code == 422
    cash = c.post_json(f"{base}/goals", {
        "name": "Cash", "metric": "CASH", "target_type": "MAINTAIN_MIN", "target": "1000",
        "period_start": "2027-01-01", "period_end": "2027-12-31"}).json()  # fmt: skip
    cash_rows = c.get(f"{base}/goals/{cash['id']}/scenario-outlooks?scenario_ids={up}").json()
    assert cash_rows[1]["applicable"] is False
    assert "13-week cash forecast" in cash_rows[1]["reason"]
    viewer = join(c, plan["ws"]["slug"], make_user("viewer@example.test"), api_client,
                  "read_only")  # fmt: skip
    assert viewer.get(f"{url}?scenario_ids={up}").status_code == 403
