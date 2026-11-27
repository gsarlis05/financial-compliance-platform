"""Reading tax rule sets (M6F-2, #147): pure data for engines, resolved by tax year."""

from calendar import monthrange
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fcp.core.errors import NotFoundError

from .corrections import Correction, Kind, all_for
from .models import TaxRuleSet

CIT = TaxRuleSet.Tax.CORPORATE_INCOME_TAX


@dataclass(frozen=True)
class Instalment:
    month: int
    day: int
    share: Decimal


@dataclass(frozen=True)
class TaxRules:
    """One rule set as plain data (pinned in the inputs of a run that uses it)."""

    id: str
    jurisdiction: str
    tax: str
    effective_from: date
    effective_to: date | None
    rate: Decimal
    loss_carryforward_years: int
    tax_year_start_month: int
    instalments: tuple[Instalment, ...]
    final_payment: tuple[int, int, int]  # years after the tax year, month, day
    verified: bool
    verification_note: str
    sources: tuple[dict[str, str], ...]

    def covers(self, day: date) -> bool:
        return self.effective_from <= day and (self.effective_to is None
                                               or day <= self.effective_to)  # fmt: skip

    def tax_year(self, year: int) -> tuple[date, date]:
        """First and last day of the tax year that starts in ``year``."""
        start = date(year, self.tax_year_start_month, 1)
        end_month = (self.tax_year_start_month - 2) % 12 + 1
        end_year = year if self.tax_year_start_month == 1 else year + 1
        return start, date(end_year, end_month, monthrange(end_year, end_month)[1])

    def instalment_dates(self, year: int) -> list[tuple[date, Decimal]]:
        start, _ = self.tax_year(year)
        out = []
        for i in self.instalments:
            y = start.year if i.month >= start.month else start.year + 1
            out.append((date(y, i.month, i.day), i.share))
        return out

    def final_payment_date(self, year: int) -> date:
        offset, month, day = self.final_payment
        return date(self.tax_year(year)[1].year + offset, month, day)

    def as_refs(self) -> dict[str, Any]:
        return {
            "id": self.id, "rate": f"{self.rate.normalize():f}",
            "loss_carryforward_years": self.loss_carryforward_years,
            "tax_year_start_month": self.tax_year_start_month,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "instalments": [[i.month, i.day, str(i.share)] for i in self.instalments],
            "final_payment": list(self.final_payment), "verified": self.verified,
        }  # fmt: skip


def _view(r: TaxRuleSet) -> TaxRules:
    return TaxRules(
        id=r.id, jurisdiction=r.jurisdiction, tax=r.tax, effective_from=r.effective_from,
        effective_to=r.effective_to, rate=r.rate,
        loss_carryforward_years=r.loss_carryforward_years,
        tax_year_start_month=r.tax_year_start_month,
        instalments=tuple(Instalment(int(i["month"]), int(i["day"]), Decimal(i["share"]))
                          for i in r.provisional_instalments),
        final_payment=(r.final_payment_year_offset, r.final_payment_month, r.final_payment_day),
        verified=r.verified, verification_note=r.verification_note,
        sources=tuple(r.sources),
    )  # fmt: skip


def _corrected(c: Correction, jurisdiction: str, until: date | None) -> TaxRules:
    v = c.values
    return TaxRules(
        id=f"CORRECTION:{c.id}", jurisdiction=jurisdiction, tax=CIT,
        effective_from=c.effective_from, effective_to=until, rate=Decimal(v["rate"]),
        loss_carryforward_years=int(v["loss_carryforward_years"]),
        tax_year_start_month=int(v["tax_year_start_month"]),
        instalments=tuple(Instalment(int(i["month"]), int(i["day"]), Decimal(i["share"]))
                          for i in v["instalments"]),
        final_payment=(int(v["final_payment"][0]), int(v["final_payment"][1]),
                       int(v["final_payment"][2])),
        verified=False, verification_note=f"Corrected by the entity: {c.source}",
        sources=({"publisher": "", "title": c.source, "url": "", "note": c.note},),
    )  # fmt: skip


def _with_corrections(base: list[TaxRules], entity_id: UUID) -> list[TaxRules]:
    """The global rule sets, replaced from each correction's start (brief 27, T-2)."""
    fixes = all_for(entity_id, Kind.CORPORATE_TAX)
    if not fixes:
        return base
    # The latest entered among corrections starting the same day.
    by_start = {c.effective_from: c for c in fixes}
    starts = sorted(by_start)
    out = []
    for r in base:  # a global set keeps the years before the first correction
        if r.effective_from >= starts[0]:
            continue
        cut = starts[0] - timedelta(days=1)
        end = cut if r.effective_to is None or r.effective_to > cut else r.effective_to
        out.append(replace(r, effective_to=end))
    for i, start in enumerate(starts):
        until = starts[i + 1] - timedelta(days=1) if i + 1 < len(starts) else None
        out.append(_corrected(by_start[start], base[0].jurisdiction if base else "", until))
    return out


def rule_sets(jurisdiction: str, tax: str = CIT, entity_id: UUID | None = None) -> list[TaxRules]:
    """The rule sets in force over time; with ``entity_id``, its corrections included."""
    base = [_view(r) for r in TaxRuleSet.objects.filter(jurisdiction=jurisdiction, tax=tax)
            .order_by("effective_from")]  # fmt: skip
    return _with_corrections(base, entity_id) if entity_id and tax == CIT else base


def rules_for(
    jurisdiction: str, day: date, tax: str = CIT, entity_id: UUID | None = None
) -> TaxRules:
    """The rule set in force on ``day`` (a day of the tax year), corrections included."""
    found = [r for r in rule_sets(jurisdiction, tax, entity_id) if r.covers(day)]
    if not found:
        raise NotFoundError(
            f"No {tax.replace('_', ' ').lower()} rules for {jurisdiction} on {day.isoformat()}."
        )
    return found[0]
