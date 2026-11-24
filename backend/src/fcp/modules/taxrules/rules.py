"""Reading tax rule sets (M6F-2, #147): pure data for engines, resolved by tax year."""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from fcp.core.errors import NotFoundError

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


def rule_sets(jurisdiction: str, tax: str = CIT) -> list[TaxRules]:
    return [_view(r) for r in TaxRuleSet.objects.filter(jurisdiction=jurisdiction, tax=tax)
            .order_by("effective_from")]  # fmt: skip


def rules_for(jurisdiction: str, day: date, tax: str = CIT) -> TaxRules:
    """The rule set in force on ``day`` (a day of the tax year)."""
    found = [r for r in rule_sets(jurisdiction, tax) if r.covers(day)]
    if not found:
        raise NotFoundError(
            f"No {tax.replace('_', ' ').lower()} rules for {jurisdiction} on {day.isoformat()}."
        )
    return found[0]
