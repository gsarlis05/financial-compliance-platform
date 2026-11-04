"""Every planning number has a nature, and natures are never mixed silently (M3-2, doc 10 P2/P3).

- ``ActualSeries``: what happened (from the ledger, through ``reporting``).
- ``PlanSeries``: one non-actual nature (committed, expected, hypothetical, budget, forecast or
  target).
- ``BlendedSeries``: actuals up to a cut-over date and a plan from then on, each point keeping its
  own nature. Only ``blend()`` makes one.

There is no ``+`` between an actual and a plan series. Type checking (mypy) rejects it, and so does
the runtime (``NatureMixError``). Plan series add only to plan series of the same nature.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Self


class Nature(StrEnum):
    ACTUAL = "ACTUAL"  # posted in the ledger
    COMMITTED = "COMMITTED"  # contractually due (an open invoice, a loan instalment)
    EXPECTED = "EXPECTED"  # likely but not contractual (a recurring cost, an estimate)
    HYPOTHETICAL = "HYPOTHETICAL"  # a what-if, never saved over the base
    BUDGET = "BUDGET"
    FORECAST = "FORECAST"
    TARGET = "TARGET"


PLAN_NATURES = frozenset(Nature) - {Nature.ACTUAL}


class NatureMixError(TypeError):
    """Numbers of different natures were combined without an explicit ``blend()``."""


@dataclass(frozen=True)
class Point:
    period: date
    value: Decimal
    nature: Nature


def _values(values: Mapping[date, Decimal] | Iterable[tuple[date, Decimal]]) -> tuple[
        tuple[date, Decimal], ...]:  # fmt: skip
    items = dict(values.items() if isinstance(values, Mapping) else values)
    for value in items.values():
        if not isinstance(value, Decimal):
            raise TypeError(f"series values are Decimal, not {type(value).__name__}")
    return tuple(sorted(items.items()))


class _Series:
    """Values per period. Immutable; arithmetic is defined by the subclasses only."""

    __slots__ = ("_items",)
    _items: tuple[tuple[date, Decimal], ...]

    def __init__(self, values: Mapping[date, Decimal] | Iterable[tuple[date, Decimal]]) -> None:
        object.__setattr__(self, "_items", _values(values))

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("series are immutable")

    @property
    def values(self) -> dict[date, Decimal]:
        return dict(self._items)

    def periods(self) -> list[date]:
        return [p for p, _ in self._items]

    def total(self) -> Decimal:
        return sum((v for _, v in self._items), Decimal(0))

    def _combine(self, other: "_Series", sign: int) -> dict[date, Decimal]:
        merged = dict(self._items)
        for period, value in other._items:
            merged[period] = merged.get(period, Decimal(0)) + sign * value
        return merged


class ActualSeries(_Series):
    __slots__ = ()
    nature = Nature.ACTUAL

    def points(self) -> list[Point]:
        return [Point(p, v, Nature.ACTUAL) for p, v in self._items]

    def _check(self, other: object) -> "ActualSeries":
        if type(other) is not ActualSeries:
            raise NatureMixError(
                f"cannot combine ACTUAL with {getattr(other, 'nature', type(other).__name__)}; "
                "use blend(actual, plan, cutover)"
            )
        return other

    def __add__(self, other: "ActualSeries") -> "ActualSeries":
        return ActualSeries(self._combine(self._check(other), 1))

    def __sub__(self, other: "ActualSeries") -> "ActualSeries":
        return ActualSeries(self._combine(self._check(other), -1))

    def __eq__(self, other: object) -> bool:
        return type(other) is ActualSeries and self._items == other._items

    def __hash__(self) -> int:
        return hash((Nature.ACTUAL, self._items))

    def __repr__(self) -> str:
        return f"ActualSeries({dict(self._items)!r})"


class PlanSeries(_Series):
    __slots__ = ("nature",)
    nature: Nature

    def __init__(
        self, nature: Nature, values: Mapping[date, Decimal] | Iterable[tuple[date, Decimal]]
    ) -> None:
        if nature not in PLAN_NATURES:
            raise NatureMixError("a plan series cannot be ACTUAL; use ActualSeries")
        super().__init__(values)
        object.__setattr__(self, "nature", Nature(nature))

    def points(self) -> list[Point]:
        return [Point(p, v, self.nature) for p, v in self._items]

    def _check(self, other: object) -> "PlanSeries":
        if type(other) is not PlanSeries or other.nature != self.nature:
            raise NatureMixError(
                f"cannot combine {self.nature} with "
                f"{getattr(other, 'nature', type(other).__name__)} without an explicit rule"
            )
        return other

    def __add__(self, other: "PlanSeries") -> "PlanSeries":
        return PlanSeries(self.nature, self._combine(self._check(other), 1))

    def __sub__(self, other: "PlanSeries") -> "PlanSeries":
        return PlanSeries(self.nature, self._combine(self._check(other), -1))

    def relabel(self, nature: Nature) -> Self:
        """The same values under another plan nature, explicitly (e.g. forecast lines of mixed
        committed and expected flows, summed per nature and then reported as FORECAST)."""
        return type(self)(nature, self._items)

    def __eq__(self, other: object) -> bool:
        return (
            type(other) is PlanSeries
            and self.nature == other.nature
            and self._items == other._items
        )

    def __hash__(self) -> int:
        return hash((self.nature, self._items))

    def __repr__(self) -> str:
        return f"PlanSeries({self.nature.value}, {dict(self._items)!r})"


@dataclass(frozen=True)
class BlendedSeries:
    """Actuals before ``cutover`` and the plan from ``cutover`` on; each point keeps its nature.
    It has no arithmetic: blend the totals you need instead."""

    cutover: date
    points: tuple[Point, ...]

    def total(self) -> Decimal:
        return sum((p.value for p in self.points), Decimal(0))

    def __add__(self, other: object) -> "BlendedSeries":
        raise NatureMixError("blended series have no arithmetic; blend the combined series")


def blend(actual: ActualSeries, plan: PlanSeries, cutover: date) -> BlendedSeries:
    """E.g. year-to-date actuals plus the rest-of-year forecast. Periods before ``cutover`` come
    from the actuals only, periods on or after it from the plan only."""
    if type(actual) is not ActualSeries or type(plan) is not PlanSeries:
        raise NatureMixError("blend(actual, plan, cutover) takes an ActualSeries and a PlanSeries")
    points = [p for p in actual.points() if p.period < cutover]
    points += [p for p in plan.points() if p.period >= cutover]
    return BlendedSeries(cutover, tuple(sorted(points, key=lambda p: p.period)))
