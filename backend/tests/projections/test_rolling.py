"""Rolling forecasts (M6-4, AC-RF1), on the books of ``test_assumptions.hist``: a 12-month set
for 2027 started from 2026 actuals (January sales 1,200; February 1,100), approved."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.core.management import call_command
from django.db import transaction

from fcp.core.errors import NotFoundError
from fcp.modules.projections import rolling
from fcp.modules.projections.runs import same_month_of_the_set
from fcp.modules.tenancy import services as tenancy

from ..ledger.test_dimensions import commit_point
from ..metrics.test_mapping import post
from .test_assumptions import books, hist, make

pytestmark = pytest.mark.django_db
__all__ = ["books", "hist"]
JAN_15, MAR_10 = date(2027, 1, 15), date(2027, 3, 10)


def setup(h: dict[str, Any]) -> dict[str, Any]:
    c, base = h["client"], h["base"]
    assert c.post_json(f"{base}/fiscal-years", {"start_date": "2027-01-01"}).status_code == 201
    s: dict[str, Any] = make(h, months=12).json()
    c.post_json(f"{base}/assumption-sets/{s['id']}/approve", {})
    configured = c.put_json(f"{base}/rolling-forecast",
                            {"assumption_set_id": s["id"], "horizon": 12})  # fmt: skip
    assert configured.status_code == 200, configured.content
    got: dict[str, Any] = configured.json()
    assert (got["configured"], got["horizon"], got["assumption_set_id"]) == (True, 12, s["id"])
    assert got["stale"] is True
    assert got["stale_reasons"] == ["not run yet"]
    return s


def refresh(h: dict[str, Any], today: date) -> Any:
    with transaction.atomic():
        ctx = tenancy.enter_workspace(h["owner"], h["ws"]["slug"])
        return rolling.refresh(ctx, h["entity"]["id"], today)


def test_rolling_runs_go_stale_and_are_rerun(hist: dict[str, Any]) -> None:
    c, base = hist["client"], hist["base"]
    setup(hist)
    first = refresh(hist, JAN_15)
    assert first is not None
    assert (first.as_of_date, first.status, first.trigger) == (date(2026, 12, 31), "VALID",
                                                               "SCHEDULE")  # fmt: skip
    assert refresh(hist, JAN_15) is None  # current
    got = c.get(f"{base}/rolling-forecast").json()
    assert (got["stale"], got["latest"]["id"]) == (False, str(first.id))

    # A posting after the watermark makes it stale; the job makes a new run and keeps the old one.
    post(hist, ("1300", "50.00", "0"), ("4000", "0", "50.00"), day="2026-12-20")
    commit_point()
    got = c.get(f"{base}/rolling-forecast").json()
    assert got["stale"] is True
    assert got["stale_reasons"] == ["new postings since the forecast was made"]
    report = rolling.refresh_all(JAN_15)
    assert (report.refreshed, report.current, report.skipped) == (1, 0, [])
    assert rolling.refresh_all(JAN_15).current == 1
    got = c.get(f"{base}/rolling-forecast").json()
    assert got["stale"] is False
    assert [(r["id"] == str(first.id), r["stale"]) for r in got["history"]] == [
        (False, False), (True, True)]  # fmt: skip
    newer = got["history"][0]
    assert newer["actuals_watermark"] > first.actuals_watermark

    # A new month: the forecast rolls to February's month end and reaches past the set, taking
    # the set's value for the same month (February 2028 = February 2027).
    later = refresh(hist, MAR_10)
    assert later is not None
    assert later.as_of_date == date(2027, 2, 28)
    assert later.input_refs["months"][-1] == "2028-02-01"
    assert str(later.supersedes_id) == newer["id"]
    statements = c.get(f"{base}/projections/{later.id}").json()
    revenue = statements["rows"]["PL.REVENUE"]
    assert (revenue[1], revenue[-1]) == ("0.00", "1100.00")  # March 2027; February 2028

    # On demand, nothing to do when current; inactive settings are skipped by the job.
    assert c.post_json(f"{base}/rolling-forecast/refresh", {}).status_code == 200
    s = c.get(f"{base}/rolling-forecast").json()
    off = {"assumption_set_id": s["assumption_set_id"], "horizon": 24, "active": False}
    assert c.put_json(f"{base}/rolling-forecast", off).status_code == 200
    assert rolling.refresh_all(MAR_10).refreshed == 0
    call_command("projections_refresh")  # the command runs one pass


def test_accuracy_compares_forecast_with_actual(hist: dict[str, Any]) -> None:
    setup(hist)
    refresh(hist, JAN_15)  # made to 31/12/2026: January 2027 sales of 1,200 expected
    post(hist, ("1300", "1000.00", "0"), ("4000", "0", "1000.00"), day="2027-01-10")
    post(hist, ("5000", "300.00", "0"), ("1300", "0", "300.00"), day="2027-01-11")
    commit_point()
    with transaction.atomic():
        ctx = tenancy.enter_workspace(hist["owner"], hist["ws"]["slug"])
        months = rolling.accuracy(ctx, hist["entity"]["id"], MAR_10)
    assert [m.month for m in months][-2:] == [date(2027, 1, 1), date(2027, 2, 1)]
    jan = months[-2]
    assert jan.actual["PL.REVENUE"] == Decimal(1000)
    assert jan.actual["PL.EBITDA"] == Decimal(700)
    assert jan.actual["BS.CASH"] == Decimal(800)  # 100 at the year end + 1,000 - 300
    (one,) = jan.comparisons["PL.REVENUE"]
    assert (one.horizon, one.forecast, one.error, one.pct) == (1, Decimal(1200), Decimal(200),
                                                               Decimal("20.00"))  # fmt: skip
    assert months[-1].comparisons["PL.REVENUE"] == ()  # no forecast made to January
    assert all(not any(m.comparisons.values()) for m in months[:-2])
    got = hist["client"].get(f"{hist['base']}/rolling-forecast/accuracy")
    assert got.status_code == 200
    assert len(got.json()) == 12


def test_settings_are_checked(hist: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    c, base = hist["client"], hist["base"]
    assert c.get(f"{base}/rolling-forecast").json()["configured"] is False
    draft = make(hist, months=12).json()
    refused = c.put_json(f"{base}/rolling-forecast",
                         {"assumption_set_id": draft["id"], "horizon": 12})  # fmt: skip
    assert refused.status_code == 409, refused.content
    too_long = {"assumption_set_id": draft["id"], "horizon": 36}
    assert c.put_json(f"{base}/rolling-forecast", too_long).status_code == 422
    setup(hist)

    def refuse(*args: Any) -> Any:
        raise NotFoundError("Workspace not found.")

    monkeypatch.setattr(rolling, "enter_workspace", refuse)
    skipped = rolling.refresh_all(JAN_15)
    assert len(skipped.skipped) == 1
    assert "Workspace not found" in skipped.skipped[0]


def test_same_month_of_the_set() -> None:
    jan, feb = date(2027, 1, 1), date(2027, 2, 1)
    drivers = {("dso", ""): {jan: Decimal(30), feb: Decimal(45)}}
    months = [date(2026, 12, 1), feb, date(2028, 1, 1), date(2029, 2, 1)]
    assert same_month_of_the_set(drivers, months) == {
        ("dso", ""): {feb: Decimal(45), date(2028, 1, 1): Decimal(30),
                      date(2029, 2, 1): Decimal(45)}}  # fmt: skip
