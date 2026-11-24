"""Goals against scenarios (M7-5, doc 10 §6.2 item 9, brief 21 §3).

A goal is evaluated now against its base (the published projection, else the approved budget or the
run rate, as usual) and against up to three **shared** scenarios side by side. For a scenario, the
goal's likely outcome takes the scenario's projected months (every income-statement line the goal
can use, from the scenario run) in place of the published projection, with method ``SCENARIO`` and
nature ``HYPOTHETICAL``. These evaluations are computed in memory: they are not stored, raise no
alert, and never change the goal (goals change only by a person's revision). Cash goals follow the
13-week cash forecast, so a scenario does not apply to them, which is said.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from fcp.core.errors import ConflictError, ValidationFailedError
from fcp.modules.calendar.api import month_end
from fcp.modules.goals.api import Outlook, outlook
from fcp.modules.projections.api import GOAL_LINES, load_input, project
from fcp.modules.reporting.api import current_watermark
from fcp.modules.tenancy.api import WorkspaceContext

from . import services
from .apply import apply
from .models import Scenario
from .runs import _refs, items_of

MAX_SCENARIOS = 3
ZERO = Decimal("0.00")


def scenario_plan(ctx: WorkspaceContext, entity_id: UUID, s: Scenario) -> Any:
    """The scenario's projected months, shaped like a published projection's plan for a goal."""
    refs = _refs(ctx, entity_id, s)
    base = load_input(ctx, entity_id, refs["base"], current_watermark(ctx, entity_id))
    final, _ = project(apply(base, items_of(refs)).inp)
    by_month = {m.month: m.pl for m in final.months}

    def plan_for(months: list[date]) -> dict[str, Any] | None:
        covered = sorted(set(months) & set(by_month))
        if not covered:
            return None
        return {
            "source": "SCENARIO",
            "versions": [{"id": str(s.id), "budget": "scenario", "number": "",
                          "fiscal_year_start": covered[0].isoformat(),
                          "fiscal_year_end": month_end(covered[-1]).isoformat()}],
            "amounts": {f"line:{code}": {m.isoformat(): str(by_month[m].get(key, ZERO))
                                         for m in covered}
                        for code, key in GOAL_LINES.items()},
        }  # fmt: skip

    return plan_for


def goal_outlooks(ctx: WorkspaceContext, entity_id: UUID, goal_id: UUID,
                  scenario_ids: list[UUID]) -> list[Outlook]:  # fmt: skip
    """The goal against its base, then against each named shared scenario (at most three)."""
    if len(scenario_ids) > MAX_SCENARIOS or len(set(scenario_ids)) != len(scenario_ids):
        message = f"scenario_ids: at most {MAX_SCENARIOS} different shared scenarios."
        raise ValidationFailedError(message, field_errors={"scenario_ids": [message]})
    scenarios = []
    for scenario_id in scenario_ids:
        s = services.get(ctx, entity_id, scenario_id, services.RUN)
        if s.status != Scenario.Status.SHARED:
            raise ConflictError(f"Share the scenario “{s.name}” before testing goals "
                                "against it.")  # fmt: skip
        scenarios.append(s)
    out = [outlook(ctx, entity_id, goal_id)]
    for s in scenarios:
        out.append(outlook(ctx, entity_id, goal_id, label=s.name,
                           plan_for=scenario_plan(ctx, entity_id, s)))  # fmt: skip
    return out
