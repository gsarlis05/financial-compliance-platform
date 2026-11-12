"""Projections as calculation runs (M6-3, AC-PJ2, AC-PJ4, AC-PJ5, AC-PJ6), on the books of
``test_assumptions.hist``: at 31/12/2026 cash 100 (2,000 received, 1,900 paid), receivables 300,
and 400 of 2026 profit not yet closed into retained earnings."""

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from fcp.core.errors import ValidationFailedError
from fcp.modules.projections import engine, runs

from ..ledger.test_dimensions import commit_point
from ..metrics.test_mapping import post
from .test_assumptions import books, hist, make

pytestmark = pytest.mark.django_db
__all__ = ["books", "hist"]


def approved(h: dict[str, Any]) -> str:
    s = make(h, months=12).json()
    assert h["client"].post_json(f"{h['base']}/assumption-sets/{s['id']}/approve",
                                 {}).status_code == 200  # fmt: skip
    return str(s["id"])


def test_run_publish_and_reproduce(hist: dict[str, Any]) -> None:
    c, base = hist["client"], hist["base"]
    draft = make(hist, months=12).json()
    refused = c.post_json(f"{base}/projections", {"assumption_set_id": draft["id"]})
    assert refused.status_code == 409, refused.content
    assert c.post_json(f"{base}/projections",
                       {"assumption_set_id": str(uuid4())}).status_code == 404  # fmt: skip

    set_id = approved(hist)
    first = c.post_json(f"{base}/projections", {"assumption_set_id": set_id})
    assert first.status_code == 201, first.content
    run = first.json()
    assert (run["status"], run["as_of_date"], run["assumption_set_id"]) == (
        "VALID", "2026-12-31", set_id)  # fmt: skip
    assert all(run["invariants"].values())

    got = c.get(f"{base}/projections/{run['id']}").json()
    opening = got["columns"][0]
    assert (opening["start"], opening["end"], opening["nature"]) == (
        "2026-12-01", "2026-12-31", "ACTUAL")  # fmt: skip
    assert {col["nature"] for col in got["columns"][1:]} == {"FORECAST"}
    assert len(got["columns"]) == 13
    rows = got["rows"]
    # AC-PJ2: period 1 opens on the actual balance sheet, line for line.
    assert (rows["BS.CASH"][0], rows["BS.AR"][0], rows["BS.EQUITY.RETAINED"][0]) == (
        "100.00", "300.00", "400.00")  # fmt: skip
    assert rows["BS.CASH"][1] == rows["CF.CLOSING_CASH"][1]
    assert got["failures"] == []
    year = c.get(f"{base}/projections/{run['id']}?granularity=YEAR").json()
    assert len(year["columns"]) == 2  # the opening and the year
    assert year["rows"]["BS.CASH"][1] == rows["BS.CASH"][12]

    # AC-PJ4: the same inputs give the same hashes.
    again = c.post_json(f"{base}/projections", {"assumption_set_id": set_id}).json()
    assert (again["input_hash"], again["output_hash"]) == (run["input_hash"], run["output_hash"])
    published = c.post_json(f"{base}/calc-runs/{run['id']}/publish", {})
    assert published.status_code == 200, published.content
    assert published.json()["is_published"] is True

    # A posting after the watermark changes neither the stored run nor its values.
    post(hist, ("1300", "50.00", "0"), ("4000", "0", "50.00"), day="2026-12-20")
    commit_point()
    assert c.get(f"{base}/projections/{run['id']}").json()["rows"] == rows
    newer = c.post_json(f"{base}/projections", {"assumption_set_id": set_id}).json()
    assert newer["actuals_watermark"] > run["actuals_watermark"]
    assert newer["input_hash"] != run["input_hash"]
    assert c.get(f"{base}/projections/{newer['id']}").json()["rows"]["BS.CASH"][0] == "150.00"
    listed = [p["id"] for p in c.get(f"{base}/projections").json()]
    assert {run["id"], again["id"], newer["id"]} <= set(listed)


def test_an_invalid_run_says_where_and_cannot_be_published(
    hist: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    c, base = hist["client"], hist["base"]
    set_id = approved(hist)
    real = engine.check

    def broken(p: engine.Projection, inp: engine.EngineInput) -> dict[str, bool]:
        p.months[2].bs["BS.CASH"] += Decimal("0.01")
        return real(p, inp)

    monkeypatch.setattr(engine, "check", broken)
    run = c.post_json(f"{base}/projections", {"assumption_set_id": set_id}).json()
    assert run["status"] == "INVALID"
    got = c.get(f"{base}/projections/{run['id']}").json()
    assert "balance_sheet_balances@2027-03" in got["failures"]
    refused = c.post_json(f"{base}/calc-runs/{run['id']}/publish", {})
    assert refused.status_code == 409, refused.content


def test_an_unmapped_balance_is_refused() -> None:
    account = uuid4()
    with pytest.raises(ValidationFailedError, match="not mapped"):
        runs.opening_balance_sheet({account: Decimal(5)}, {})
    assert runs.opening_balance_sheet({account: Decimal(0)}, {}) == {}
    income, cash = uuid4(), uuid4()
    found = runs.opening_balance_sheet({income: Decimal(-70), cash: Decimal(70)},
                                       {str(income): "PL", str(cash): "BS.CASH"})  # fmt: skip
    assert found == {"BS.EQUITY.RETAINED": Decimal(70), "BS.CASH": Decimal(70)}
