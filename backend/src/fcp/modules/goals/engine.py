"""Goal baselines and evaluations as calculation runs (M4-6, doc 10 §6.2, AC-GO1 to AC-GO5).

``GOAL_BASELINE`` computes a goal's starting value once, when the goal is created: the metric over
the same months one year earlier (for a balance, the balance on the day the goal starts).

``GOAL_EVAL`` evaluates a goal at an as-of date, from posted actuals pinned to the run's
watermark and from snapshots stored in the run's inputs (account mapping, the approved budget,
the cash forecast), so a stored evaluation never changes:

1. **Actual to date:** the metric over the window's months that have ended (the cut-over is the
   last month end on or before the as-of date), with % of the target achieved and % of time
   elapsed.
2. **Likely outcome:** actuals to the cut-over, then for the remaining months the latest published
   projection where one reaches them (M6-5), otherwise the current approved annual budget, and
   where neither covers a month the trailing 3-month run rate of each account.
   Balances after the cut-over are held at their latest actual value. Cash goals use the latest
   13-week cash forecast (week-end closing cash). The method is stated with every outcome.
3. **Gap:** target - likely outcome, and target - actual.
4. **Required performance:**
   - additive metrics: the remaining amount, and the required monthly run rate against the
     projected and the historical (trailing 3 months) run rate;
   - ratios that are a division: the numerator needed with the projected denominator held, and
     the denominator needed with the projected numerator held (both stated);
   - any ratio: the uniform % change of one driver line over the remaining months, within ±100%,
     by bisection (to 0.01 percentage points, at most 60 steps), otherwise "not achievable within
     bounds" (AC-GO3);
   - cash thresholds: the first projected breach and the minimum additional inflow.
5. **Status:** on track when the outcome meets the target (direction-adjusted); at risk when it
   misses by no more than the materiality threshold (a fraction of |target|); off track otherwise.
6. **Trend:** the metric month by month (to date, then projected), each point with its nature.
7. **Contribution analysis (AC-GO5):** the outcome against the budget (or, without one, the same
   months a year earlier). Each taxonomy line's effect is the change when only that line takes
   its outcome value (one at a time); for a ratio the effects need not add up, and what is left
   is shown as an explicit residual.
"""

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fcp.modules.calendar.api import add_months, month_end, month_start
from fcp.modules.kpi.api import (
    Account,
    Evaluated,
    cutoffs,
    evaluate_formula,
    matches,
    period_months,
)
from fcp.modules.metrics.api import (
    Nature,
    Output,
    RunInputs,
    Source,
    Value,
    ratio_parts,
    register_engine,
)
from fcp.modules.reporting.api import actuals_monthly, opening_net
from fcp.modules.tenancy.api import WorkspaceContext

BASELINE_KIND, EVAL_KIND = "GOAL_BASELINE", "GOAL_EVAL"
ZERO, ONE = Decimal(0), Decimal(1)
PLACES = Decimal("1e-20")
MAX_SOURCES = 60
BISECT_STEP = Decimal("0.0001")  # 0.01 percentage points of the driver change
BISECT_MAX = 60
STATUSES = ("ON_TRACK", "AT_RISK", "OFF_TRACK", "UNDETERMINED")
HELD = "Balances after the cut-over are held at their latest actual value"

Flows = dict[tuple[str, date], Decimal]
Balances = dict[date, dict[str, Decimal]]


def cut_over(as_of: date) -> date:
    """The last month end on or before ``as_of``."""
    return as_of if as_of == month_end(as_of) else month_start(as_of) - timedelta(days=1)


def _q(value: Decimal) -> Decimal:
    return value.quantize(PLACES)


METHODS = {
    "ACTUALS": "The period has ended: actuals only",
    "BUDGET": "then the approved budget",
    "BUDGET_AND_RUN_RATE": "then the approved budget, and the 3-month run rate where the budget "
    "does not cover a month",
    "RUN_RATE": "then each account's 3-month run rate (no approved budget)",
    "PROJECTION": "then the published projection",
    "PROJECTION_RUN_RATE": "then the published projection, and the 3-month run rate where it "
    "does not cover a month",
    "CASH_FORECAST": "then the 13-week cash forecast",
    "HELD": "then held at the latest actual value (no cash forecast)",
}


def method_note(method: str, cut: date) -> str:
    """How the likely outcome was projected, in words (shown with every outcome)."""
    words = METHODS.get(method, "")
    return words if method == "ACTUALS" else f"Actuals to {cut.isoformat()}, {words}"


@dataclass(frozen=True)
class Data:
    flows: Flows  # (account id, month) -> net debit
    balances: Balances  # month start -> account id -> net debit before it


def _load(ctx: WorkspaceContext, inputs: RunInputs, first: date, last: date) -> Data:
    """Posted monthly flows from ``first`` to ``last`` (month starts) and the balances at every
    month start from ``first`` to the month after ``last``, at the run's watermark."""
    flows: Flows = {}
    if last >= first:
        facts = actuals_monthly(
            ctx,
            inputs.legal_entity_id,
            date_from=first,
            date_to=month_end(last),
            watermark=inputs.actuals_watermark,
        ).facts
        flows = {(str(f.account_id), f.period): f.net_debit for f in facts}  # fmt: skip
    balances: Balances = {}
    month = first
    while month <= add_months(last, 1):
        _, net = opening_net(ctx, inputs.legal_entity_id, before=month,
                             watermark=inputs.actuals_watermark)  # fmt: skip
        balances[month] = {str(a): v for a, v in net.items()}
        month = add_months(month, 1)
    return Data(flows, balances)


def _accounts(refs: Mapping[str, Any]) -> dict[str, Account]:
    return {a: Account(*row) for a, row in refs["accounts"].items()}


def _lineage(sources: dict[str, Decimal]) -> tuple[Source, ...]:
    out = []
    for ref, amount in sorted(sources.items())[:MAX_SOURCES]:
        if ref.startswith("operational:"):
            kind, note = "MANUAL", ""
        elif ref.startswith(("account:plan:", "account:proj:", "account:rate:")):
            kind = "ASSUMPTION"
            note = {"plan": "budget", "proj": "published projection"}.get(
                ref.split(":")[1], "run rate (3 months)"
            )
        else:
            kind, note = "ACTUAL", ""
        out.append(Source(kind, ref[:200], _q(amount), note))
    return tuple(out)


# --- the baseline -----------------------------------------------------------------------------


class GoalBaselineEngine:
    kind = BASELINE_KIND
    version = "1"

    def load(self, ctx: WorkspaceContext, inputs: RunInputs) -> Data:
        start = date.fromisoformat(inputs.refs["date_from"])
        end = date.fromisoformat(inputs.refs["date_to"])
        return _load(ctx, inputs, add_months(start, -12), month_start(end))

    def compute(self, inputs: RunInputs, data: Data) -> Output:
        refs = inputs.refs
        start, end = date.fromisoformat(refs["date_from"]), date.fromisoformat(refs["date_to"])
        found = evaluate_formula(
            refs["formula"], date_from=start, date_to=end, accounts=_accounts(refs),
            flows=data.flows, balances=data.balances, operational=refs.get("operational", {}),
        )  # fmt: skip
        value = Value(
            "goal.baseline", start, Nature.ACTUAL,
            None if found.value is None else _q(found.value), found.unit, period_end=end,
            nm_reason=found.nm_reason[:200],
            lineage=(Source("FORMULA", refs["metric_ref"][:200]),
                     *(Source("FORMULA", c[:200], note="reference") for c in found.calls),
                     *_lineage(found.sources)),
        )  # fmt: skip
        return Output((value,), {})


# --- the evaluation ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Goal:
    kind: str
    formula: str
    start: date
    end: date
    target_type: str
    target: Decimal
    at_least: bool
    materiality: Decimal
    driver: str

    @classmethod
    def of(cls, refs: dict[str, Any]) -> "Goal":
        g = refs["goal"]
        return cls(
            g["kind"], g["formula"], date.fromisoformat(g["period_from"]),
            date.fromisoformat(g["period_to"]), g["target_type"], Decimal(g["target"]),
            g["direction"] == "AT_LEAST", Decimal(g["materiality"]), g["driver"],
        )  # fmt: skip

    def meets(self, value: Decimal | None) -> bool:
        if value is None:
            return False
        return value >= self.target if self.at_least else value <= self.target

    def status(self, value: Decimal | None) -> str:
        if value is None:
            return "UNDETERMINED"
        short = self.target - value if self.at_least else value - self.target
        if short <= 0:
            return "ON_TRACK"
        return "AT_RISK" if short <= self.materiality * abs(self.target) else "OFF_TRACK"


class _Book:
    """Actual and projected data for one evaluation, as the KPI functions read it."""

    def __init__(self, refs: dict[str, Any], data: Data) -> None:
        self.goal = Goal.of(refs)
        self.refs = refs
        self.accounts = _accounts(refs)
        self.operational = refs.get("operational", {})
        self.cut = date.fromisoformat(refs["cut"])  # last actual month end
        self.last_actual = month_start(self.cut)
        self.held_at = self.cut + timedelta(days=1)  # latest actual balance date
        # Actuals to the cut-over (the projection and the actual to date never see later
        # postings); ``self.loaded`` keeps everything loaded, for the prior-year comparison.
        self.loaded = data
        self.actual = Data(
            {k: v for k, v in data.flows.items() if k[1] <= self.last_actual}, data.balances
        )
        self.months = period_months(self.goal.start, month_start(self.goal.end))
        self.remaining = [m for m in self.months if m > self.last_actual]
        self.plan_months, self.plan_flows = self._plan()
        self.rate_flows = self._run_rate()
        self.projected_flows: Flows = dict(data.flows)
        for m in self.remaining:
            source = self.plan_flows if m in self.plan_months else self.rate_flows
            for (account, month), amount in source.items():
                if month == m:
                    self.projected_flows[(account, m)] = amount

    # projection inputs -----------------------------------------------------------------------

    def _plan(self) -> tuple[set[date], Flows]:
        plan = self.refs.get("plan")
        if not plan:
            return set(), {}
        covered: set[date] = set()
        for v in plan["versions"]:
            covered |= set(
                period_months(
                    date.fromisoformat(v["fiscal_year_start"]),
                    month_start(date.fromisoformat(v["fiscal_year_end"])),
                )
            )
        flows: Flows = {}
        lines = self.refs.get("lines", {})
        for subject, per_month in plan["amounts"].items():
            kind, _, ref = subject.partition(":")
            if kind == "line" and ref in lines:
                section, credit = lines[ref]
                pseudo = f"{self.plan_prefix}:{ref}"
                self.accounts[pseudo] = Account(ref, section, credit, True)
            elif kind == "account" and ref in self.accounts:
                real = self.accounts[ref]
                pseudo, credit = f"{self.plan_prefix}:{ref}", real.credit_normal
                self.accounts[pseudo] = real
            else:
                continue
            for month, amount in per_month.items():
                natural = Decimal(amount)
                flows[(pseudo, date.fromisoformat(month))] = -natural if credit else natural
        return covered & set(self.remaining), flows

    def _run_rate(self) -> Flows:
        trailing = [add_months(self.last_actual, -i) for i in range(3)]
        totals: dict[str, Decimal] = defaultdict(Decimal)
        for (account, month), amount in self.actual.flows.items():
            if month in trailing:
                totals[account] += amount
        flows: Flows = {}
        for account, total in totals.items():
            if not total or account not in self.accounts:
                continue
            pseudo = f"rate:{account}"
            self.accounts[pseudo] = self.accounts[account]
            for m in self.remaining:
                flows[(pseudo, m)] = total / 3
        return flows

    @property
    def method(self) -> str:
        if not self.remaining:
            return "ACTUALS"
        if self.goal.kind == "BALANCE":
            return "CASH_FORECAST" if self.refs.get("forecast") else "HELD"
        if self.plan_prefix == "proj":  # a published projection (M6-5)
            if len(self.plan_months) == len(self.remaining):
                return "PROJECTION"
            return "PROJECTION_RUN_RATE" if self.plan_months else "RUN_RATE"
        if len(self.plan_months) == len(self.remaining):
            return "BUDGET"
        return "BUDGET_AND_RUN_RATE" if self.plan_months else "RUN_RATE"

    @property
    def plan_prefix(self) -> str:
        plan = self.refs.get("plan") or {}
        return "proj" if plan.get("source") == "PROJECTION" else "plan"

    @property
    def projected_nature(self) -> Nature:
        if not self.remaining:
            return Nature.ACTUAL
        return Nature.BUDGET if self.method == "BUDGET" else Nature.FORECAST

    def note(self) -> str:
        return method_note(self.method, self.cut)

    # evaluation ------------------------------------------------------------------------------

    def balance_at(self, day: date) -> dict[str, Decimal]:
        return self.actual.balances.get(min(day, self.held_at), {})

    def evaluate(self, start: date, end: date, flows: Flows,
                 balance: Callable[[date], dict[str, Decimal]] | None = None,
                 formula: str | None = None, accounts: dict[str, Account] | None = None,
                 ) -> Evaluated:  # fmt: skip
        read = balance or self.balance_at
        return evaluate_formula(
            formula or self.goal.formula, date_from=start, date_to=end,
            accounts=accounts or self.accounts, flows=flows,
            balances={d: read(d) for d in cutoffs(start, end).values()},
            operational=self.operational,
        )  # fmt: skip

    def scaled(self, key: str, change: Decimal) -> Flows:
        """The projection with ``key``'s remaining-month flows changed by ``change``."""
        later = set(self.remaining)
        return {
            (a, m): v * (ONE + change)
            if m in later and matches(self.accounts[a], key)
            else v
            for (a, m), v in self.projected_flows.items()
        }  # fmt: skip


# --- outputs -----------------------------------------------------------------------------------


class _Out:
    def __init__(self, goal: Goal) -> None:
        self.goal = goal
        self.values: list[Value] = []

    def add(  # noqa: PLR0913 (keyword-only details of a value)
        self, key: str, nature: Nature, found: Decimal | Evaluated | None, unit: str, *,
        nm: str = "", start: date | None = None, end: date | None = None,
        granularity: str = "POINT", dims: tuple[str, ...] = (),
        lineage: tuple[Source, ...] = (),
    ) -> None:  # fmt: skip
        if isinstance(found, Evaluated):
            value, nm, unit = found.value, nm or found.nm_reason, found.unit
            lineage = lineage + _lineage(found.sources)
        else:
            value = found
        if value is None and not nm:
            nm = "Not meaningful"
        self.values.append(Value(
            key, start or self.goal.start, nature, None if value is None else _q(value), unit,
            period_end=end or self.goal.end, granularity=granularity,
            nm_reason="" if value is not None else nm[:200], dimensions=dims, lineage=lineage,
        ))  # fmt: skip


def _diff(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or b is None else a - b


def _ratio(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return None if a is None or not b else a / b


class GoalEvalEngine:
    kind = EVAL_KIND
    version = "1"

    def load(self, ctx: WorkspaceContext, inputs: RunInputs) -> Data:
        g = inputs.refs["goal"]
        start = date.fromisoformat(g["period_from"])
        cut = date.fromisoformat(inputs.refs["cut"])
        # A year back for the comparison, and 3 months before the cut-over for the run rate.
        first = min(add_months(start, -15), add_months(month_start(cut), -3))
        # Through the cut-over, and through the comparison year's last month (it may end later).
        g_end = month_start(date.fromisoformat(g["period_to"]))
        return _load(ctx, inputs, first, max(month_start(cut), add_months(g_end, -12)))

    def compute(self, inputs: RunInputs, data: Data) -> Output:
        book = _Book(dict(inputs.refs), data)
        goal, out = book.goal, _Out(book.goal)
        out.add("goal.target", Nature.TARGET, goal.target, inputs.refs["goal"]["unit"],
                dims=(goal.target_type, "AT_LEAST" if goal.at_least else "AT_MOST"))  # fmt: skip
        g = inputs.refs["goal"]
        out.add("goal.baseline", Nature.ACTUAL,
                None if g["baseline"] is None else Decimal(g["baseline"]), g["unit"],
                nm=g["baseline_nm"] or "",
                lineage=(Source("RESULT", f"calc_run:{g['baseline_run']}"),))  # fmt: skip
        if goal.kind == "BALANCE":
            actual, projected = self._balance(book, out)
        else:
            actual, projected = self._flows(book, out)
        status = goal.status(projected)
        unit = next(v.unit for v in out.values if v.series_key == "goal.projected")
        out.add("goal.gap", Nature.TARGET, _diff(goal.target, projected), unit,
                nm="The likely outcome is not meaningful", dims=("PROJECTED",))  # fmt: skip
        out.add("goal.gap", Nature.TARGET, _diff(goal.target, actual), unit,
                nm="The actual value is not meaningful", dims=("ACTUAL",))  # fmt: skip
        out.add("goal.status", book.projected_nature, Decimal(STATUSES.index(status)), "count",
                dims=(status, book.method), lineage=(Source("FORMULA", "goal.status",
                note=f"materiality {goal.materiality}"),))  # fmt: skip
        if goal.kind != "BALANCE":
            self._required(book, out, actual, projected)
            self._contribution(book, out, projected)
            self._trend(book, out)
        checks = {
            "contributions_sum_to_total": self._sums(out),
            "statuses_known": status in STATUSES,
        }
        return Output(tuple(out.values), checks)

    # actual and projected ---------------------------------------------------------------------

    def _flows(self, book: _Book, out: _Out) -> tuple[Decimal | None, Decimal | None]:
        goal = book.goal
        actual_end = min(book.cut, goal.end)
        if book.cut < goal.start:
            # Nothing has happened yet: an additive metric is 0, anything else has no value.
            actual: Decimal | Evaluated | None = ZERO if goal.kind == "ADDITIVE" else None
            out.add("goal.actual", Nature.ACTUAL, actual, "EUR" if goal.kind == "ADDITIVE"
                    else "ratio", nm="No month of the period has ended yet")  # fmt: skip
            actual_value = actual if isinstance(actual, Decimal) else None
        else:
            found = book.evaluate(goal.start, actual_end, book.actual.flows)
            out.add("goal.actual", Nature.ACTUAL, found, "", end=actual_end)
            actual_value = found.value
        projected = book.evaluate(goal.start, goal.end, book.projected_flows)
        out.add("goal.projected", book.projected_nature, projected, "",
                dims=("BLENDED", book.method) if book.remaining else ("ACTUAL",),
                lineage=(Source("FORMULA", "goal.projected", note=book.note()[:200]),
                         Source("FORMULA", "held", note=HELD)))  # fmt: skip
        elapsed = [m for m in book.months if m <= book.last_actual]
        total_days = (goal.end - goal.start).days + 1
        done_days = (actual_end - goal.start).days + 1 if elapsed else 0
        out.add("goal.time_elapsed", Nature.ACTUAL, Decimal(done_days) / Decimal(total_days),
                "ratio", end=actual_end if elapsed else goal.start)  # fmt: skip
        if goal.kind == "ADDITIVE":
            out.add("goal.achieved", Nature.ACTUAL, _ratio(actual_value, goal.target), "ratio",
                    nm="The target is zero")  # fmt: skip
        return actual_value, projected.value

    def _balance(  # noqa: PLR0912 (actual points, forecast points, then the threshold)
        self, book: _Book, out: _Out
    ) -> tuple[Decimal | None, Decimal | None]:
        """Cash: month ends to date, then the forecast's week-end closings in the window."""
        goal = book.goal
        current = book.evaluate(month_start(book.cut), book.cut, book.actual.flows)
        out.add("goal.actual", Nature.ACTUAL, current, "", end=book.cut,
                start=month_start(book.cut))  # fmt: skip
        points: list[tuple[date, Decimal, Nature]] = []
        for m in book.months:
            if m > book.last_actual:
                break
            found = book.evaluate(m, month_end(m), book.actual.flows)
            if found.value is not None:
                points.append((month_end(m), found.value, Nature.ACTUAL))
        forecast = book.refs.get("forecast")
        for end_iso, closing in (forecast or {}).get("weeks", []):
            day = date.fromisoformat(end_iso)
            if book.cut < day <= goal.end:
                points.append((day, Decimal(closing), Nature.FORECAST))
        for day, amount, nature in points:
            out.add("goal.trend", nature, amount, "EUR", start=day, end=day,
                    granularity="MONTH" if nature == Nature.ACTUAL else "WEEK")  # fmt: skip
        later = [p for p in points if p[0] > book.cut]
        maintain = goal.target_type in ("MAINTAIN_MIN", "MAINTAIN_MAX")
        if maintain:
            # Throughout the window: the worst month end so far or forecast week.
            pick = min if goal.target_type == "MAINTAIN_MIN" else max
            candidates = [p[1] for p in points] or (
                [current.value] if current.value is not None else []
            )
            projected = pick(candidates, default=None)
        elif later:
            projected = later[-1][1]
        else:
            projected = current.value
        nature = Nature.FORECAST if later else Nature.ACTUAL
        note = book.note()
        if later and later[-1][0] < goal.end and goal.target_type == "ABSOLUTE":
            note += "; beyond the forecast horizon the last forecast value is held"
        used = (
            (Source("RESULT", f"calc_run:{forecast['run_id']}", note="13-week cash forecast"),)
            if forecast
            else ()
        )
        out.add("goal.projected", nature, projected, "EUR",
                dims=("BLENDED", book.method) if book.remaining else ("ACTUAL",),
                lineage=(Source("FORMULA", "goal.projected", note=note[:200]), *used))  # fmt: skip
        breach = next(((d, v) for d, v, _ in points if not goal.meets(v)), None)
        if maintain:
            if breach is not None:
                when = Nature.FORECAST if breach[0] > book.cut else Nature.ACTUAL
                out.add("goal.required.breach", when, breach[1], "EUR", start=breach[0],
                        end=breach[0])  # fmt: skip
            worst = projected
            if worst is not None:
                need = goal.target - worst if goal.at_least else worst - goal.target
                key = "goal.required.inflow" if goal.at_least else "goal.required.reduction"
                out.add(key, Nature.TARGET, max(need, ZERO), "EUR",
                        lineage=(Source("FORMULA", "threshold - worst balance"),))  # fmt: skip
        elif projected is not None:
            out.add("goal.required.inflow", Nature.TARGET, goal.target - projected, "EUR")
        return current.value, projected

    # required performance (goal-seek) ---------------------------------------------------------

    def _required(self, book: _Book, out: _Out, actual: Decimal | None,
                  projected: Decimal | None) -> None:  # fmt: skip
        goal, n = book.goal, len(book.remaining)
        ended = "The period has ended"
        if goal.kind == "ADDITIVE":
            remaining = _diff(goal.target, actual)
            out.add("goal.required.remaining", Nature.TARGET, remaining, "EUR")
            rule = (Source("FORMULA", "(target - actual) / remaining months"),)
            out.add("goal.required.run_rate", Nature.TARGET,
                    remaining / n if remaining is not None and n else None, "EUR", nm=ended,
                    lineage=rule)  # fmt: skip
            out.add("goal.projected_run_rate", book.projected_nature,
                    (projected - actual) / n if projected is not None and actual is not None
                    and n else None, "EUR", nm=ended)  # fmt: skip
            first = add_months(book.last_actual, -2)
            trailing = book.evaluate(first, book.cut, book.actual.flows)
            out.add("goal.historical_run_rate", Nature.ACTUAL,
                    None if trailing.value is None else trailing.value / 3, "EUR",
                    nm=trailing.nm_reason, start=first, end=book.cut)  # fmt: skip
            return
        parts = ratio_parts(goal.formula)
        if parts is not None:
            numerator = book.evaluate(goal.start, goal.end, book.projected_flows, formula=parts[0])
            denominator = book.evaluate(goal.start, goal.end, book.projected_flows,
                                        formula=parts[1])  # fmt: skip
            out.add("goal.required.numerator", Nature.TARGET,
                    None if denominator.value is None else goal.target * denominator.value,
                    numerator.unit, nm="The projected denominator is not meaningful",
                    lineage=(Source("FORMULA", parts[0][:200], note="numerator needed, holding "
                                    "the projected denominator constant"),))  # fmt: skip
            out.add("goal.required.denominator", Nature.TARGET,
                    _ratio(numerator.value, goal.target), denominator.unit,
                    nm="Not meaningful for a target of zero",
                    lineage=(Source("FORMULA", parts[1][:200], note="denominator needed, holding "
                                    "the projected numerator constant"),))  # fmt: skip
            out.add("goal.projected_part", book.projected_nature, numerator, "",
                    dims=("NUMERATOR",))  # fmt: skip
            out.add("goal.projected_part", book.projected_nature, denominator, "",
                    dims=("DENOMINATOR",))  # fmt: skip
        driver = goal.driver or ("REVENUE" if "flow(" in goal.formula else "")
        if driver:
            change, reason = self._seek(book, driver)
            out.add("goal.required.driver_change", Nature.TARGET, change, "ratio", nm=reason,
                    dims=(driver,), lineage=(Source("FORMULA", f"bisection on {driver}"[:200],
                    note=f"{driver} changed by the same % in every remaining month; every other "
                    "line as projected; " + HELD.lower()),))  # fmt: skip

    def _seek(self, book: _Book, driver: str) -> tuple[Decimal | None, str]:
        """The smallest uniform change of ``driver`` (within ±100%) that meets the target."""
        goal = book.goal

        def value(change: Decimal) -> Decimal | None:
            flows = book.scaled(driver, change)
            return book.evaluate(goal.start, goal.end, flows).value

        if goal.meets(value(ZERO)):
            return ZERO, ""
        if not book.remaining:
            return None, "The period has ended: no month is left to change"
        if goal.meets(value(ONE)):
            low, high = ZERO, ONE
        elif goal.meets(value(-ONE)):
            low, high = ZERO, -ONE
        else:
            return None, f"Not achievable within ±100% of {driver}"
        for _ in range(BISECT_MAX):
            if abs(high - low) < BISECT_STEP:
                break
            middle = (low + high) / 2
            if goal.meets(value(middle)):
                high = middle
            else:
                low = middle
        return high, ""

    # contribution analysis --------------------------------------------------------------------

    def _comparison(self, book: _Book) -> tuple[str, Flows, Callable[[date], dict[str, Decimal]]]:
        months = set(book.months)
        if book.plan_flows:
            flows = {k: v for k, v in book.plan_flows.items() if k[1] in months}
            return "BUDGET", flows, book.balance_at
        flows = {(a, add_months(m, 12)): v for (a, m), v in book.loaded.flows.items()
                 if add_months(m, 12) in months}  # fmt: skip

        def prior(day: date) -> dict[str, Decimal]:
            earlier = add_months(day, -12)
            if earlier in book.loaded.balances:
                return book.loaded.balances[earlier]
            return book.balance_at(earlier)

        return "PRIOR_YEAR", flows, prior

    def _contribution(self, book: _Book, out: _Out, projected: Decimal | None) -> None:
        goal = book.goal
        basis, flows, balance = self._comparison(book)
        base = book.evaluate(goal.start, goal.end, flows, balance)
        nature = Nature.BUDGET if basis == "BUDGET" else Nature.ACTUAL
        out.add("goal.comparison", nature, base, "", dims=(basis,))
        if base.value is None or projected is None:
            return
        outcome = book.evaluate(goal.start, goal.end, book.projected_flows)
        codes = sorted({self._code(book, ref) for ref in [*outcome.sources, *base.sources]} - {""})
        total = projected - base.value
        effects = ZERO
        for code in codes:

            def mixed_balance(d: date, code: str = code) -> dict[str, Decimal]:
                ours, theirs = book.balance_at(d), balance(d)
                keys = set(ours) | set(theirs)
                return {a: (ours if self._is(book, a, code) else theirs).get(a, ZERO)
                        for a in keys}  # fmt: skip

            mixed = {k: v for k, v in flows.items() if not self._is(book, k[0], code)}
            mixed |= {k: v for k, v in book.projected_flows.items() if self._is(book, k[0], code)}
            found = book.evaluate(goal.start, goal.end, mixed, mixed_balance)
            if found.value is None:
                continue
            effect = found.value - base.value
            if effect:
                effects += effect
                out.add("goal.contribution", book.projected_nature, effect, base.unit,
                        dims=(code, basis))  # fmt: skip
        out.add("goal.contribution.residual", book.projected_nature, total - effects, base.unit,
                dims=(basis,), lineage=(Source("FORMULA", "total - sum of line effects",
                note="interaction between lines (0 for an additive metric)"),))  # fmt: skip
        out.add("goal.contribution.total", book.projected_nature, total, base.unit, dims=(basis,))

    @staticmethod
    def _code(book: _Book, ref: str) -> str:
        if not ref.startswith("account:"):
            return ""
        account = book.accounts.get(ref.removeprefix("account:").rsplit(":", 1)[0])
        return account.code if account else ""

    @staticmethod
    def _is(book: _Book, account_id: str, code: str) -> bool:
        account = book.accounts.get(account_id)
        return account is not None and account.code == code

    @staticmethod
    def _sums(out: _Out) -> bool:
        def one(key: str) -> Decimal | None:
            return next((v.value for v in out.values if v.series_key == key), None)

        total = one("goal.contribution.total")
        if total is None:
            return True
        parts = [v.value for v in out.values if v.series_key == "goal.contribution"
                 and v.value is not None]  # fmt: skip
        residual = one("goal.contribution.residual") or ZERO
        return sum(parts, ZERO) + residual == total

    # trend ----------------------------------------------------------------------------------

    def _trend(self, book: _Book, out: _Out) -> None:
        goal = book.goal
        for m in book.months:
            nature = Nature.ACTUAL if m <= book.last_actual else book.projected_nature
            flows = book.actual.flows if m <= book.last_actual else book.projected_flows
            found = book.evaluate(goal.start, month_end(m), flows)
            out.add("goal.trend", nature, found.value, found.unit, nm=found.nm_reason,
                    start=m, end=month_end(m), granularity="MONTH")  # fmt: skip


BASELINE_ENGINE = register_engine(GoalBaselineEngine())
EVAL_ENGINE = register_engine(GoalEvalEngine())
