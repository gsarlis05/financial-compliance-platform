"""VAT periods from an entity's schemes (pure date logic, V1-2).

A scheme says that from ``effective_from`` (the first day of a month) the periods last ``months``
months, one after another. A later scheme starts where a period of the earlier one would have
started, so no period is ever cut in two.
"""

from dataclasses import dataclass
from datetime import date

ALLOWED_MONTHS = (1, 2, 3, 4, 6, 12)


@dataclass(frozen=True)
class Scheme:
    months: int
    effective_from: date


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    months: int


def add_months(day: date, months: int) -> date:
    """The same day ``months`` later; used only with the first day of a month."""
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, day.day)


def _months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * 12 + later.month - earlier.month


def scheme_problem(existing: list[Scheme], new: Scheme) -> str | None:
    """Why ``new`` cannot follow ``existing`` (None when it can)."""
    if new.months not in ALLOWED_MONTHS:
        return "A VAT period lasts 1, 2, 3, 4, 6 or 12 months."
    if new.effective_from.day != 1:
        return "VAT periods start on the first day of a month."
    if not existing:
        return None
    last = max(existing, key=lambda s: s.effective_from)
    if new.effective_from <= last.effective_from:
        return (
            "A change of VAT periods takes effect after the current one, which started on "
            f"{last.effective_from.isoformat()}."
        )
    if _months_between(last.effective_from, new.effective_from) % last.months:
        return (
            "A change of VAT periods must start where a current period would start "
            f"(every {last.months} months from {last.effective_from.isoformat()})."
        )
    return None


def periods(schemes: list[Scheme], start: date, end: date) -> list[Period]:
    """Every VAT period that overlaps ``start``..``end``, oldest first."""
    ordered = sorted(schemes, key=lambda s: s.effective_from)
    found: list[Period] = []
    for i, scheme in enumerate(ordered):
        limit = ordered[i + 1].effective_from if i + 1 < len(ordered) else None
        begin = scheme.effective_from
        while (limit is None or begin < limit) and begin <= end:
            following = add_months(begin, scheme.months)
            if following > start:
                found.append(
                    Period(begin, date.fromordinal(following.toordinal() - 1), scheme.months)
                )
            begin = following
    return found


def period_of(schemes: list[Scheme], day: date) -> Period | None:
    """The VAT period that contains ``day`` (None before the first scheme)."""
    found = periods(schemes, day, day)
    return found[0] if found else None
