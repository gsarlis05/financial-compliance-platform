"""Customer payment behaviour: observed days late, minimum sample, override (M3-6, AC-CW2)."""

from typing import Any

import pytest

from .test_open_items import ar, books, invoice, items, receipt

pytestmark = pytest.mark.django_db
__all__ = ["ar", "books"]


def allocate(ar: dict[str, Any], ref: str, amount: str, paid_on: str) -> None:
    """Settle part of invoice ``ref`` with a receipt dated ``paid_on``."""
    receipt(ar, "C1", paid_on, amount, f"pay-{ref}-{paid_on}")
    open_now = items(ar, "2027-12-31", counterparty_id=ar["parties"]["C1"])
    inv = next(i for i in open_now if i["reference"] == ref)
    pay = next(i for i in open_now if i["reference"] == f"pay-{ref}-{paid_on}")
    made = ar["client"].post_json(
        f"{ar['base']}/allocations",
        {"invoice_line_id": inv["line_id"], "payment_line_id": pay["line_id"], "amount": amount},
    )
    assert made.status_code == 201, made.content


def behaviour(ar: dict[str, Any], as_of: str) -> dict[str, dict[str, Any]]:
    response = ar["client"].get(f"{ar['base']}/payment-behaviour", {"as_of": as_of})
    assert response.status_code == 200, response.content
    return {b["counterparty_code"]: b for b in response.json()}


@pytest.fixture
def paid(ar: dict[str, Any]) -> dict[str, Any]:
    """C1: A paid 10 days late, B 2 days late, C 5 days early, D in two parts (20 days late)."""
    invoice(ar, "C1", "2026-01-01", "1000.00", "A", due="2026-01-31")
    invoice(ar, "C1", "2026-02-01", "3000.00", "B", due="2026-02-28")
    invoice(ar, "C1", "2026-03-01", "1000.00", "C", due="2026-03-31")
    invoice(ar, "C1", "2026-04-01", "500.00", "D", due="2026-04-30")
    allocate(ar, "A", "1000.00", "2026-02-10")
    allocate(ar, "B", "3000.00", "2026-03-02")
    allocate(ar, "C", "1000.00", "2026-03-26")
    allocate(ar, "D", "200.00", "2026-05-05")
    allocate(ar, "D", "300.00", "2026-05-20")
    return ar


def test_amount_weighted_days_late(paid: dict[str, Any]) -> None:
    # (1000 x 10 + 3000 x 2 + 1000 x -5) / 5000 = 2.2 -> 2
    c1 = behaviour(paid, "2026-04-30")["C1"]
    assert (c1["observed_days_late"], c1["sample"], c1["days_late"]) == (2, 3, 2)
    assert c1["note"] == "Observed over 3 invoices settled in the last 12 months."


def test_an_invoice_counts_once_fully_settled(paid: dict[str, Any]) -> None:
    assert behaviour(paid, "2026-05-10")["C1"]["sample"] == 3  # D only partly paid
    # + 500 x 20: 21000 / 5500 = 3.82 -> 4
    c1 = behaviour(paid, "2026-05-31")["C1"]
    assert (c1["observed_days_late"], c1["sample"]) == (4, 4)


def test_trailing_twelve_months_and_minimum_sample(paid: dict[str, Any]) -> None:
    # A was settled on 2026-02-10, more than 12 months before: (6000 - 5000 + 10000) / 4500
    later = behaviour(paid, "2027-02-15")["C1"]
    assert (later["observed_days_late"], later["sample"]) == (2, 3)
    gone = behaviour(paid, "2027-06-01")["C1"]
    assert (gone["observed_days_late"], gone["sample"], gone["days_late"]) == (None, 0, 0)
    assert "at least 3 needed" in gone["note"]
    few = behaviour(paid, "2026-03-01")["C1"]  # only A settled so far (B is paid on 2 March)
    assert (few["observed_days_late"], few["sample"], few["days_late"]) == (None, 1, 0)
    everyone = behaviour(paid, "2026-05-31")
    assert set(everyone) == {"C1", "C2"}  # customers only, not the supplier
    assert everyone["C2"]["sample"] == 0


def test_override_replaces_the_observed_value(paid: dict[str, Any]) -> None:
    url = f"{paid['base']}/counterparties/{paid['parties']['C1']}"
    set_to = paid["client"].patch_json(url, {"days_late_override": 15})
    assert set_to.status_code == 200, set_to.content
    assert set_to.json()["days_late_override"] == 15
    c1 = behaviour(paid, "2026-05-31")["C1"]
    assert (c1["observed_days_late"], c1["override"], c1["days_late"]) == (4, 15, 15)
    assert c1["note"].startswith("Override set by a user.")
    cleared = paid["client"].patch_json(url, {"days_late_override": None})
    assert cleared.json()["days_late_override"] is None
    assert behaviour(paid, "2026-05-31")["C1"]["days_late"] == 4
    assert paid["client"].patch_json(url, {"days_late_override": 400}).status_code == 422
    early = paid["client"].patch_json(url, {"days_late_override": -10})
    assert early.json()["days_late_override"] == -10
