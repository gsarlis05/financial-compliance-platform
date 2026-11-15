"""Depreciation commencement (IAS 16) and tax capital allowances (M6F-3, #148; owner decisions
D1-D3). Every figure is worked out by hand in the comments."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from django.db import DatabaseError, transaction

from fcp.core.db.rls import set_context
from fcp.modules.assets.allowances import AllowanceRate, allowance_schedule
from fcp.modules.assets.models import CapitalAllowanceClass, FixedAsset
from fcp.modules.assets.schedule import (
    DECLINING_BALANCE,
    FULL_MONTH,
    NEXT_MONTH,
    PRORATA_DAYS,
    AssetTerms,
    schedule,
)

from ..ledger.conftest import books
from .test_assets import asset_body, reg

pytestmark = pytest.mark.django_db
__all__ = ["books", "reg"]
D = Decimal


def terms(**extra: Any) -> AssetTerms:
    base: dict[str, Any] = {"acquired_on": date(2026, 3, 1), "cost": D(12000),
                            "residual": D(0), "life_months": 12,
                            "available_on": date(2026, 3, 16)}  # fmt: skip
    return AssetTerms(**{**base, **extra})


def test_pro_rata_from_the_available_for_use_date() -> None:
    rows = schedule(terms(commencement=PRORATA_DAYS))
    # March has 31 days; in use from the 16th: 16/31 of 1,000 = 516.13. Then 1,000 a month to
    # February 2027, and March 2027 takes the remainder 12,000 - 516.13 - 11,000 = 483.87.
    assert (rows[0].month, rows[-1].month) == (date(2026, 3, 1), date(2027, 3, 1))
    assert len(rows) == 13
    assert (rows[0].depreciation, rows[1].depreciation) == (D("516.13"), D("1000.00"))
    assert rows[-1].depreciation == D("483.87")
    assert sum(r.depreciation for r in rows) == D(12000)


def test_next_month_and_full_month_conventions() -> None:
    nxt = schedule(terms(commencement=NEXT_MONTH))
    assert (nxt[0].month, len(nxt), nxt[0].depreciation) == (date(2026, 4, 1), 12, D(1000))
    full = schedule(terms(commencement=FULL_MONTH))
    assert (full[0].month, full[-1].month, len(full)) == (date(2026, 3, 1), date(2027, 2, 1), 12)
    # Without an available-for-use date, depreciation starts from the acquisition date.
    plain = schedule(terms(available_on=None, commencement=FULL_MONTH))
    assert plain[0].month == date(2026, 3, 1)
    with pytest.raises(ValueError, match="before it is acquired"):
        schedule(terms(available_on=date(2026, 2, 1)))


def test_declining_balance_pro_rata() -> None:
    rows = schedule(terms(commencement=PRORATA_DAYS, method=DECLINING_BALANCE,
                          annual_rate=D("0.24")))  # fmt: skip
    # 12,000 x 24% / 12 x 16/31 = 123.87; then 11,876.13 x 2% = 237.52.
    assert (rows[0].depreciation, rows[1].depreciation) == (D("123.87"), D("237.52"))
    assert sum(r.depreciation for r in rows) == D(12000)  # the last month takes the rest


def test_capital_allowances_by_tax_year() -> None:
    used = date(2026, 3, 10)
    months_in_use = [AllowanceRate(date(2020, 1, 1), D("0.2"), "MONTHS_IN_USE")]
    rows = allowance_schedule(D(10000), used, months_in_use)
    # 2026: 10,000 x 20% x 10/12 (March to December) = 1,666.67; then 2,000 a year until the
    # written-down value is used up: 333.33 in 2031.
    assert [(r.tax_year, r.allowance) for r in rows] == [
        (2026, D("1666.67")), (2027, D(2000)), (2028, D(2000)), (2029, D(2000)),
        (2030, D(2000)), (2031, D("333.33"))]  # fmt: skip
    assert rows[-1].written_down == 0
    full = allowance_schedule(D(10000), used, [AllowanceRate(date(2020, 1, 1), D("0.2"))])
    assert [r.allowance for r in full] == [D(2000)] * 5
    none_first = allowance_schedule(
        D(10000), used, [AllowanceRate(date(2020, 1, 1), D("0.2"), "NONE")]
    )
    assert [r.allowance for r in none_first][:2] == [D(0), D(2000)]
    # A new rate from 2028 (10%), and a disposal in 2029: nothing from the year of disposal.
    changed = allowance_schedule(D(10000), used, [
        AllowanceRate(date(2020, 1, 1), D("0.2")), AllowanceRate(date(2028, 1, 1), D("0.1"))],
        disposed_on=date(2029, 5, 31))  # fmt: skip
    assert [(r.tax_year, r.allowance) for r in changed] == [
        (2026, D(2000)), (2027, D(2000)), (2028, D(1000))]  # fmt: skip
    assert allowance_schedule(D(10000), used, []) == []  # no class rate: no allowances


def test_register_with_commencement_and_allowances(reg: dict[str, Any]) -> None:
    c, base = reg["client"], reg["base"]
    cls = {"code": "MACH", "name": "Machinery (Demo)", "annual_rate": "20",
           "first_year": "FULL_YEAR", "effective_from": "2020-01-01",
           "source": "Rate entered for the test; to be confirmed by a tax adviser"}  # fmt: skip
    made = c.post_json(f"{base}/capital-allowance-classes", cls)
    assert made.status_code == 201, made.content
    assert c.post_json(f"{base}/capital-allowance-classes", cls).status_code == 422
    for bad in ({"source": " "}, {"annual_rate": "120"}):
        later = {**cls, **bad, "effective_from": "2030-01-01"}
        assert c.post_json(f"{base}/capital-allowance-classes", later).status_code == 422
    body = asset_body(reg, code="M-1", cost="12000.00", useful_life_months=12,
                      acquired_on="2026-03-01", available_on="2026-03-16",
                      commencement="PRORATA_DAYS", allowance_class_code="MACH")  # fmt: skip
    asset = c.post_json(f"{base}/fixed-assets", body)
    assert asset.status_code == 201, asset.content
    a = asset.json()
    assert (a["available_on"], a["commencement"], a["allowance_class_code"]) == (
        "2026-03-16", "PRORATA_DAYS", "MACH")  # fmt: skip
    sched = c.get(f"{base}/fixed-assets/{a['id']}/schedule").json()
    assert sched["rows"][0]["depreciation"] == "516.13"
    assert [x["allowance"] for x in sched["allowances"]] == ["2400.00"] * 5
    assert "balancing" in sched["allowance_rules"]
    bad = c.post_json(f"{base}/fixed-assets", {**body, "code": "M-2", "available_on": "2026-02-01"})
    assert bad.status_code == 422
    unknown = {**body, "code": "M-3", "allowance_class_code": "NOPE"}
    assert c.post_json(f"{base}/fixed-assets", unknown).status_code == 422
    # The allowance class can change after depreciation is prepared; accounting terms cannot.
    set_context(tenant_id=UUID(reg["ws"]["id"]))
    FixedAsset.objects.filter(id=a["id"]).update(locked_at="2026-04-01T00:00:00Z")
    changed = c.put_json(f"{base}/fixed-assets/{a['id']}/allowance-class",
                         {"allowance_class_code": ""})  # fmt: skip
    assert changed.status_code == 200, changed.content
    assert changed.json()["allowance_class_code"] == ""
    with pytest.raises(DatabaseError, match="locked"), transaction.atomic():
        FixedAsset.objects.filter(id=a["id"]).update(commencement="NEXT_MONTH")
    with pytest.raises(DatabaseError, match="never changed"), transaction.atomic():
        CapitalAllowanceClass.objects.filter(code="MACH").update(name="x")
