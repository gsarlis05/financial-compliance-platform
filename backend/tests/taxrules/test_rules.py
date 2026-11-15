"""Tax rule sets (M6F-2, #147): sourced, versioned, jurisdiction-specific data, resolved by tax
year, never overlapping, and unverified until a professional confirms them (#154)."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.db import DatabaseError, transaction

from fcp.core.errors import NotFoundError
from fcp.modules.taxrules.api import Instalment, TaxRules, rule_sets, rules_for
from fcp.modules.taxrules.models import TaxRuleSet

from ..ledger.conftest import books

pytestmark = pytest.mark.django_db
__all__ = ["books"]


def test_cyprus_rules_by_tax_year() -> None:
    before, after = rules_for("CY", date(2025, 6, 30)), rules_for("CY", date(2026, 1, 1))
    assert (before.id, before.rate, before.loss_carryforward_years) == (
        "CY:CIT:2020", Decimal("0.125"), 5)  # fmt: skip
    assert (after.id, after.rate, after.loss_carryforward_years) == (
        "CY:CIT:2026", Decimal("0.15"), 7)  # fmt: skip
    assert after.instalment_dates(2026) == [
        (date(2026, 7, 31), Decimal("0.5")), (date(2026, 12, 31), Decimal("0.5"))]  # fmt: skip
    assert after.final_payment_date(2026) == date(2027, 8, 1)
    assert after.tax_year(2026) == (date(2026, 1, 1), date(2026, 12, 31))
    assert not before.verified
    assert not after.verified
    assert "#154" in after.verification_note
    assert all(s["url"].startswith("https://") for s in after.sources)
    assert [r.id for r in rule_sets("CY")] == ["CY:CIT:2020", "CY:CIT:2026"]
    with pytest.raises(NotFoundError, match="No corporate income tax rules for CY"):
        rules_for("CY", date(2019, 12, 31))  # earlier years are not seeded
    assert after.as_refs()["rate"] == "0.15"


def test_a_tax_year_that_is_not_the_calendar_year() -> None:
    rules = TaxRules(
        id="XX:CIT:2026", jurisdiction="XX", tax="CORPORATE_INCOME_TAX",
        effective_from=date(2026, 7, 1), effective_to=None, rate=Decimal("0.2"),
        loss_carryforward_years=3, tax_year_start_month=7,
        instalments=(Instalment(12, 31, Decimal("0.5")), Instalment(3, 31, Decimal("0.5"))),
        final_payment=(0, 12, 31), verified=False, verification_note="test", sources=(),
    )  # fmt: skip
    assert rules.tax_year(2026) == (date(2026, 7, 1), date(2027, 6, 30))
    assert rules.instalment_dates(2026) == [
        (date(2026, 12, 31), Decimal("0.5")), (date(2027, 3, 31), Decimal("0.5"))]  # fmt: skip
    assert rules.final_payment_date(2026) == date(2027, 12, 31)


def test_the_database_keeps_rule_sets_consistent() -> None:
    base: dict[str, Any] = {
        "jurisdiction": "CY", "tax": "CORPORATE_INCOME_TAX", "rate": Decimal("0.2"),
        "loss_carryforward_years": 7, "final_payment_year_offset": 1, "final_payment_month": 8,
        "final_payment_day": 1, "sources": [{"publisher": "test"}],
    }  # fmt: skip
    with pytest.raises(DatabaseError, match="overlaps"), transaction.atomic():
        TaxRuleSet.objects.create(id="CY:CIT:X", effective_from=date(2025, 6, 1), **base)
    with pytest.raises(DatabaseError, match="taxrules_verified_by_whom"), transaction.atomic():
        TaxRuleSet.objects.filter(id="CY:CIT:2026").update(verified=True)
    with pytest.raises(DatabaseError, match="taxrules_rate_fraction"), transaction.atomic():
        TaxRuleSet.objects.filter(id="CY:CIT:2026").update(rate=Decimal(15))


def test_the_api_shows_sources_and_status(books: dict[str, Any]) -> None:
    got = books["client"].get(f"{books['base']}/tax-rules")
    assert got.status_code == 200, got.content
    latest = got.json()[-1]
    assert (latest["id"], latest["rate"], latest["verified"]) == ("CY:CIT:2026", "0.15", False)
    assert latest["provisional_instalments"] == [
        {"month": 7, "day": 31, "share": "0.5"},
        {"month": 12, "day": 31, "share": "0.5"},
    ]
    assert latest["final_payment"] == "01/08 of the year 1 after the tax year"
    assert latest["sources"][0]["publisher"] == "EY Global Tax News"
