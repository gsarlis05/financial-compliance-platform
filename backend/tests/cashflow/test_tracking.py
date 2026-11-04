"""Forecast freshness, refresh, history and accuracy (M3-8, AC-CW6)."""

from datetime import date
from typing import Any

import pytest
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from fcp.core.errors import NotFoundError
from fcp.modules.cashflow import tracking
from fcp.modules.tenancy import services as tenancy

from ..registers.test_open_items import ar, books, post
from .test_forecast import fc

pytestmark = pytest.mark.django_db
__all__ = ["ar", "books", "fc"]


def run(fc: dict[str, Any], as_of: str) -> dict[str, Any]:
    made = fc["client"].post_json(f"{fc['base']}/cash-forecasts", {"as_of": as_of})
    assert made.status_code == 201, made.content
    result: dict[str, Any] = made.json()
    return result


def latest(fc: dict[str, Any]) -> dict[str, Any]:
    response = fc["client"].get(f"{fc['base']}/cash-forecasts/latest")
    assert response.status_code == 200, response.content
    result: dict[str, Any] = response.json()
    return result


def test_the_latest_forecast_says_when_it_is_out_of_date(fc: dict[str, Any]) -> None:
    today = timezone.localdate().isoformat()
    run(fc, today)
    assert (latest(fc)["stale"], latest(fc)["stale_reasons"]) == (False, [])
    # A posting (e.g. a receipt) makes it stale at once.
    post(
        fc,
        today,
        [{"account_id": "1300", "debit": "25.00"}, {"account_id": "4000", "credit": "25.00"}],
    )
    assert latest(fc)["stale_reasons"] == ["new postings since the forecast was made"]
    run(fc, today)
    assert latest(fc)["stale"] is False
    # Inputs that are not postings: a manual item, a setting, an open-item dispute.
    fc["client"].post_json(
        f"{fc['base']}/cash-items",
        {"day": today, "amount": "5.00", "category": "OTHER", "reason": "x"},
    )
    assert latest(fc)["stale_reasons"] == [
        "open items, commitments, settings or reconciliations changed"
    ]
    run(fc, today)
    fc["client"].put_json(f"{fc['base']}/cash-forecast-settings", {"minimum_cash": "1.00"})
    assert latest(fc)["stale"] is True


def test_refresh_supersedes_and_marks_earlier_runs_stale(fc: dict[str, Any]) -> None:
    first = run(fc, "2026-11-04")
    with transaction.atomic():
        ctx = tenancy.enter_workspace(fc["owner"], fc["ws"]["slug"])
        entity = fc["entity"]["id"]
        assert tracking.refresh(ctx, entity, date(2026, 11, 4)) is None  # current
        made = tracking.refresh(ctx, entity, date(2026, 11, 5))  # the as-of date has passed
        assert made is not None
        assert (made.as_of_date, made.trigger, str(made.supersedes_id)) == (
            date(2026, 11, 5),
            "SCHEDULE",
            first["run_id"],
        )
    history = fc["client"].get(f"{fc['base']}/cash-forecasts/history").json()
    assert [(h["as_of"], h["stale"], h["trigger"]) for h in history] == [
        ("2026-11-05", False, "SCHEDULE"),
        ("2026-11-04", True, "USER"),
    ]
    assert history[0]["supersedes_id"] == first["run_id"]
    assert history[1]["opening_cash"] == "10000.00"
    assert history[1]["first_shortfall"] == "2026-11-04"
    # On demand: nothing to do when current.
    now = fc["client"].post_json(f"{fc['base']}/cash-forecasts/refresh", {})
    assert now.status_code in (200, 204)


def test_the_scheduled_job(fc: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    run(fc, "2026-11-04")
    report = tracking.refresh_all(date(2026, 11, 4))
    assert (report.refreshed, report.current, report.skipped) == (0, 1, [])
    post(
        fc,
        "2026-11-04",
        [{"account_id": "1300", "debit": "1.00"}, {"account_id": "4000", "credit": "1.00"}],
    )
    report = tracking.refresh_all(date(2026, 11, 4))
    assert (report.refreshed, report.current) == (1, 0)
    assert tracking.refresh_all(date(2026, 11, 4)).current == 1

    def refuse(*args: Any) -> Any:
        raise NotFoundError("Workspace not found.")

    monkeypatch.setattr(tracking, "enter_workspace", refuse)
    skipped = tracking.refresh_all(date(2026, 11, 9))
    assert len(skipped.skipped) == 1
    assert "Workspace not found" in skipped.skipped[0]
    monkeypatch.undo()
    call_command("cashflow_refresh")  # the command runs one pass


def test_accuracy_compares_with_actual_movements(fc: dict[str, Any]) -> None:
    # Forecasts made in week 41 (5 Oct) and week 42 (12 Oct): nothing scheduled for weeks 42-43.
    run(fc, "2026-10-05")
    run(fc, "2026-10-12")
    post(
        fc,
        "2026-10-13",
        [{"account_id": "1300", "debit": "400.00"}, {"account_id": "4000", "credit": "400.00"}],
    )
    result = (
        fc["client"]
        .get(f"{fc['base']}/cash-forecasts/accuracy", {"as_of": "2026-10-26", "weeks": 3})
        .json()
    )
    weeks = {w["label"]: w for w in result["weeks"]}
    assert list(weeks) == ["2026-W41", "2026-W42", "2026-W43"]
    assert weeks["2026-W41"]["comparisons"] == []  # no forecast made the week before
    w42 = weeks["2026-W42"]
    assert w42["actual"] == "400.00"
    assert [
        (c["horizon_weeks"], c["forecast"], c["error"], c["ape_percent"])
        for c in w42["comparisons"]
    ] == [(1, "0.00", "-400.00", "100.00")]
    w43 = weeks["2026-W43"]
    assert w43["actual"] == "0.00"
    assert w43["comparisons"][0]["ape_percent"] is None  # not meaningful: actual 0
    assert result["mape_percent"] == {"1": "100.00", "4": None, "13": None}
    assert result["samples"] == {"1": 1, "4": 0, "13": 0}
    assert "not yet categorised" in result["note"]
