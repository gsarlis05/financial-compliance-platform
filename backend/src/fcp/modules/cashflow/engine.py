"""The 13-week cash forecast engine, CASH_13W (M3-7, doc 10 §3.1-§3.3, AC-CW1-CW4).

``load`` reads only the opening cash, from the ledger pinned at the run's watermark (through
``reporting``). Everything else was copied into the run's inputs when it was prepared
(``services.prepare``): open receivables and payables with their expected dates, obligation, loan
and tax flows with their version IDs, manual items, settings and warnings. ``compute`` is pure.

Per ISO-week bucket (``calendar.weekly_buckets``):
- the opening, and flows by direction, category and nature;
- inflows, outflows (positive), net and closing;
- the minimum cash, headroom (closing - minimum), undrawn facilities and liquidity (closing +
  facility limits);
- a shortfall flag when the closing is below the minimum.

The first shortfall date is the first day the running balance falls below the minimum. Flows dated
before the as-of date are overdue and fall in the first bucket, flagged. Flows are dated and never
pro-rated.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fcp.modules.calendar.api import Bucket, allocate, weekly_buckets
from fcp.modules.metrics.api import Nature, Output, RunInputs, Source, Value, register_engine
from fcp.modules.reporting.api import opening_net
from fcp.modules.tenancy.api import WorkspaceContext

KIND = "CASH_13W"
ZERO = Decimal(0)
SOURCE_KINDS = {
    "RECEIVABLE": "OPEN_ITEM",
    "PAYABLE": "OPEN_ITEM",
    "OBLIGATION": "SCHEDULE",
    "DEBT": "SCHEDULE",
    "TAX": "SCHEDULE",
    "MANUAL": "MANUAL",
    "WHATIF": "OVERRIDE",  # added by a what-if (M3-9), never stored
}


@dataclass(frozen=True)
class Flow:
    day: date
    amount: Decimal  # receipts positive, payments negative
    nature: Nature
    category: str
    source: str  # RECEIVABLE | PAYABLE | OBLIGATION | DEBT | TAX | MANUAL
    ref: str

    @property
    def direction(self) -> str:
        return "IN" if self.amount > 0 else "OUT"


def parse_flows(refs: dict[str, Any]) -> list[Flow]:
    return [
        Flow(
            date.fromisoformat(f["day"]),
            Decimal(f["amount"]),
            Nature(f["nature"]),
            f["category"],
            f["source"],
            f["ref"],
        )
        for f in refs.get("flows", [])
    ]


def _week(  # noqa: PLR0913 (a value builder with keyword options)
    bucket: Bucket,
    key: str,
    nature: Nature,
    value: Decimal | None,
    *,
    lineage: tuple[Source, ...] = (),
    dims: tuple[str, ...] = (),
    unit: str = "EUR",
) -> Value:
    return Value(
        key,
        bucket.start,
        nature,
        value,
        unit,
        period_end=bucket.end,
        granularity="WEEK",
        dimensions=dims,
        lineage=lineage,
    )


class CashForecast:
    kind = KIND
    version = "1"

    def load(self, ctx: WorkspaceContext, inputs: RunInputs) -> dict[str, Decimal]:
        """Opening cash per cash account: everything posted up to the as-of date, at the run's
        watermark."""
        _, net = opening_net(
            ctx,
            inputs.legal_entity_id,
            before=inputs.as_of + timedelta(days=1),
            watermark=inputs.actuals_watermark,
        )
        return {a: net.get(UUID(a), ZERO) for a in inputs.refs.get("cash_accounts", [])}

    def compute(self, inputs: RunInputs, data: dict[str, Decimal]) -> Output:  # noqa: PLR0912, PLR0915 (one linear pass)
        refs = inputs.refs
        as_of = inputs.as_of
        buckets = weekly_buckets(as_of, int(refs.get("weeks", 13)))
        minimum = Decimal(refs.get("minimum_cash", "0"))
        limits = Decimal(refs.get("facility_limits", "0"))
        flows = parse_flows(dict(refs))
        # Overdue flows are shown in the first bucket (brief §3); flows past the horizon are out.
        placed = allocate(flows, buckets, lambda f: max(f.day, as_of))
        values: list[Value] = []

        opening = sum(data.values(), ZERO)
        accounts = tuple(Source("ACTUAL", f"account:{a}", v) for a, v in sorted(data.items()))
        for source in accounts:
            values.append(
                Value(
                    "cash.opening_account",
                    as_of,
                    Nature.ACTUAL,
                    source.amount,
                    "EUR",
                    dimensions=(source.ref.removeprefix("account:"),),
                    lineage=(source,),
                )
            )

        checks = {
            "closing_is_opening_plus_net": True,
            "opening_is_previous_closing": True,
            "buckets_hold_every_flow": True,
        }
        balance = opening
        previous_closing: Decimal | None = None
        first_shortfall: tuple[date, Decimal] | None = None
        if opening < minimum:
            first_shortfall = (as_of, opening)
        in_horizon = ZERO
        for bucket in buckets:
            week = placed.within[bucket.index]
            bucket_open = balance
            if previous_closing is not None and bucket_open != previous_closing:
                checks["opening_is_previous_closing"] = False
            values.append(
                _week(
                    bucket,
                    "cash.opening",
                    Nature.ACTUAL if bucket.index == 1 else Nature.FORECAST,
                    bucket_open,
                    lineage=accounts
                    if bucket.index == 1
                    else (Source("RESULT", "cash.closing", bucket_open),),
                )
            )
            groups: dict[tuple[str, str, Nature], list[Flow]] = defaultdict(list)
            for flow in week:
                groups[(flow.direction, flow.category, flow.nature)].append(flow)
            inflows = outflows = ZERO
            for (direction, category, nature), members in sorted(groups.items()):
                total = sum((f.amount for f in members), ZERO)
                if direction == "IN":
                    inflows += total
                else:
                    outflows -= total
                values.append(
                    _week(
                        bucket,
                        "cash.flow",
                        nature,
                        abs(total),
                        dims=(direction, category),
                        lineage=tuple(
                            Source(
                                SOURCE_KINDS[f.source],
                                f.ref,
                                f.amount,
                                "overdue" if f.day < as_of else "",
                            )
                            for f in members
                        ),
                    )
                )
            # The first day within the week that the running balance drops below the minimum.
            for day in sorted({max(f.day, as_of) for f in week}):
                balance += sum((f.amount for f in week if max(f.day, as_of) == day), ZERO)
                if first_shortfall is None and balance < minimum:
                    first_shortfall = (day, balance)
            net = inflows - outflows
            closing = bucket_open + net
            if closing != balance:
                checks["closing_is_opening_plus_net"] = False
            in_horizon += net
            previous_closing = closing
            undrawn = max(limits - max(-closing, ZERO), ZERO)
            for key, value, unit in (
                ("cash.inflows", inflows, "EUR"),
                ("cash.outflows", outflows, "EUR"),
                ("cash.net", net, "EUR"),
                ("cash.closing", closing, "EUR"),
                ("cash.headroom", closing - minimum, "EUR"),
                ("cash.undrawn_facilities", undrawn, "EUR"),
                ("cash.liquidity", closing + limits, "EUR"),
                ("cash.shortfall", Decimal(1 if closing < minimum else 0), "count"),
            ):
                values.append(
                    _week(
                        bucket,
                        key,
                        Nature.FORECAST,
                        value,
                        unit=unit,
                        lineage=(Source("RESULT", "cash.opening"), Source("RESULT", "cash.flow"))
                        if key == "cash.closing"
                        else (),
                    )
                )
            values.append(
                _week(
                    bucket,
                    "cash.minimum",
                    Nature.TARGET,
                    minimum,
                    lineage=(Source("ASSUMPTION", "settings:minimum_cash"),),
                )
            )
        # Independently of the buckets: every flow due up to the horizon's end is counted once.
        expected = sum((f.amount for f in flows if f.day <= buckets[-1].end), ZERO)
        if expected != in_horizon or balance != opening + in_horizon:
            checks["buckets_hold_every_flow"] = False
        overdue = [f for f in flows if f.day < as_of]
        values.append(
            Value(
                "cash.overdue",
                as_of,
                Nature.FORECAST,
                sum((f.amount for f in overdue), ZERO),
                "EUR",
                nm_reason="",
                lineage=tuple(Source(SOURCE_KINDS[f.source], f.ref, f.amount) for f in overdue),
            )
        )
        if first_shortfall is not None:
            values.append(
                Value(
                    "cash.first_shortfall",
                    first_shortfall[0],
                    Nature.FORECAST,
                    first_shortfall[1],
                    "EUR",
                    lineage=(Source("ASSUMPTION", "settings:minimum_cash", minimum),),
                )
            )
        values.append(
            Value(
                "cash.beyond_horizon",
                buckets[-1].end + timedelta(days=1),
                Nature.FORECAST,
                sum((f.amount for f in placed.after), ZERO),
                "EUR",
            )
        )
        return Output(tuple(values), checks)


ENGINE = register_engine(CashForecast())
