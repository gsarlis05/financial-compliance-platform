"""Fixed-asset register (M6-1, AC-FA1, AC-FA2): depreciation is prepared as a draft entry that
needs the normal approval, a month is never prepared twice, terms lock once depreciation is
prepared, disposals stop depreciation, and the database keeps the history."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from django.db import DatabaseError, transaction

from fcp.core.db.rls import set_context
from fcp.modules.assets.models import DepreciationRunLine, FixedAsset

from ..ledger.conftest import books, join
from ..ledger.test_closing import no_approval
from ..ledger.test_dimensions import commit_point
from ..ledger.test_entries import act

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books"]


def asset_body(b: dict[str, Any], **extra: Any) -> dict[str, Any]:
    acc = b["accounts"]
    return {"code": "VAN-1", "name": "Delivery van (Demo)", "category": "VEHICLES",
            "asset_account_id": acc["1010"]["id"], "accumulated_account_id": acc["1019"]["id"],
            "expense_account_id": acc["6600"]["id"], "acquired_on": "2026-01-15",
            "cost": "24000.00", "residual_value": "0", "useful_life_months": 48,
            **extra}  # fmt: skip


@pytest.fixture
def reg(books: dict[str, Any]) -> dict[str, Any]:
    no_approval(books)
    c, base = books["client"], books["base"]
    made = c.post_json(f"{base}/fixed-assets", asset_body(books))
    assert made.status_code == 201, made.content
    return {**books, "van": made.json()}


def test_register_schedule_and_draft_depreciation(reg: dict[str, Any]) -> None:
    c, base, van = reg["client"], reg["base"], reg["van"]
    assert (van["status"], van["locked"]) == ("ACTIVE", False)
    on = {a["code"]: a for a in c.get(f"{base}/fixed-assets?as_of=2026-01-31").json()}
    assert (on["VAN-1"]["book_value"], on["VAN-1"]["accumulated"]) == ("24000.00", "0.00")
    later = c.get(f"{base}/fixed-assets?as_of=2026-06-30").json()[0]
    assert (later["book_value"], later["accumulated"]) == ("21500.00", "2500.00")
    sched = c.get(f"{base}/fixed-assets/{van['id']}/schedule").json()
    assert len(sched["rows"]) == 48
    assert sched["rows"][0] == {"month": "2026-02-01", "opening": "24000.00",
                                "depreciation": "500.00", "closing": "23500.00",
                                "accumulated": "500.00", "entry_id": None}  # fmt: skip
    assert "month after acquisition" in sched["convention"]

    # Prepared as a draft (AC-FA2): nothing is posted by the register.
    run = c.post_json(f"{base}/depreciation-runs", {"month": "2026-02-10"})
    assert run.status_code == 201, run.content
    body = run.json()
    assert (body["month"], body["total"], body["assets"], body["entry_status"]) == (
        "2026-02-01",
        "500.00",
        1,
        "DRAFT",
    )
    entry = c.get(f"{base}/journal-entries/{body['entry_id']}").json()
    assert (entry["status"], entry["accounting_date"]) == ("DRAFT", "2026-02-28")
    lines = {(ln["account_id"], ln["debit"], ln["credit"]) for ln in entry["lines"]}
    acc = reg["accounts"]
    assert lines == {(acc["6600"]["id"], "500.00", "0.00"), (acc["1019"]["id"], "0.00", "500.00")}
    tb = c.get(f"{base}/reports/trial-balance?as_of=2026-12-31").json()
    assert all(r["account_id"] != acc["6600"]["id"] for r in tb["rows"])  # not posted

    # Never twice for the same month; the terms are now locked.
    again = c.post_json(f"{base}/depreciation-runs", {"month": "2026-02-01"})
    assert again.status_code == 409, again.content
    assert again.json()["detail"] == (
        "Depreciation for 02/2026 is already prepared; its entry is draft. Void or reject that "
        "entry to prepare the month again."
    )
    assert entry["description"] == "Depreciation 02/2026 (1 asset, fixed-asset register)"
    assert c.get(f"{base}/fixed-assets").json()[0]["locked"] is True
    corrected = c.put_json(f"{base}/fixed-assets/{van['id']}", asset_body(reg, cost="25000.00"))
    assert corrected.status_code == 409, corrected.content

    # A voided draft frees the month: it can be prepared again, and the first run is kept.
    assert act(reg, body["entry_id"], "void").status_code == 200
    redo = c.post_json(f"{base}/depreciation-runs", {"month": "2026-02-01"})
    assert redo.status_code == 201, redo.content
    runs = c.get(f"{base}/depreciation-runs").json()
    assert [(r["cancelled"], r["entry_status"]) for r in runs] == [(False, "DRAFT"),
                                                                    (True, "VOID")]  # fmt: skip

    # Posted through the normal workflow, it reaches the books.
    assert act(reg, redo.json()["entry_id"], "post").status_code == 200
    commit_point()
    tb = c.get(f"{base}/reports/trial-balance?as_of=2026-02-28").json()
    dep = next(r for r in tb["rows"] if r["account_id"] == acc["6600"]["id"])
    assert dep["debit"] == "500.00"
    sched = c.get(f"{base}/fixed-assets/{van['id']}/schedule").json()
    assert sched["rows"][0]["entry_id"] == redo.json()["entry_id"]


def test_several_assets_one_entry_and_disposal(reg: dict[str, Any]) -> None:
    c, base = reg["client"], reg["base"]
    laptop = c.post_json(f"{base}/fixed-assets", asset_body(
        reg, code="IT-7", name="Laptops (Demo)", category="IT_EQUIPMENT", acquired_on="2026-02-03",
        cost="3600.00", residual_value="0", useful_life_months=36, method="DECLINING_BALANCE",
        annual_rate="40"))  # fmt: skip
    assert laptop.status_code == 201, laptop.content
    assert laptop.json()["annual_rate"] == "40.00"
    # March: van 500.00, laptops 3,600 x 40% / 12 = 120.00.
    run = c.post_json(f"{base}/depreciation-runs", {"month": "2026-03-01"}).json()
    assert (run["total"], run["assets"]) == ("620.00", 2)

    # A disposal before an already prepared month is refused; afterwards it stops depreciation.
    van = reg["van"]["id"]
    early = c.post_json(f"{base}/fixed-assets/{van}/dispose",
                        {"disposed_on": "2026-03-10", "proceeds": "20000.00"})  # fmt: skip
    assert early.status_code == 422, early.content
    sold = c.post_json(f"{base}/fixed-assets/{van}/dispose",
                       {"disposed_on": "2026-04-20", "proceeds": "22000.00"})  # fmt: skip
    assert sold.status_code == 200, sold.content
    # Book value at the end of March: 24,000 - 2 x 500 = 23,000; loss of 1,000.
    assert sold.json()["disposal_gain"] == "-1000.00"
    assert c.post_json(f"{base}/fixed-assets/{van}/dispose",
                       {"disposed_on": "2026-05-01"}).status_code == 409  # fmt: skip
    april = c.post_json(f"{base}/depreciation-runs", {"month": "2026-04-01"}).json()
    assert (april["total"], april["assets"]) == ("116.00", 1)  # laptops only: 3,480 x 40% / 12
    listed = {a["code"]: a for a in c.get(f"{base}/fixed-assets?as_of=2026-05-31").json()}
    assert listed["VAN-1"]["status"] == "DISPOSED"
    # Nothing left to depreciate before any asset was bought.
    none = c.post_json(f"{base}/depreciation-runs", {"month": "2025-12-01"})
    assert none.status_code == 422, none.content


def test_validation_permissions_and_history(reg: dict[str, Any], make_user: Make,
                                            api_client: Make) -> None:  # fmt: skip
    c, base, acc = reg["client"], reg["base"], reg["accounts"]
    for bad, field in (
        ({"expense_account_id": acc["1010"]["id"]}, "expense_account_id"),
        ({"asset_account_id": acc["6600"]["id"]}, "asset_account_id"),
        ({"accumulated_account_id": acc["1010"]["id"]}, "accumulated_account_id"),
        ({"residual_value": "30000.00"}, "residual_value"),
        ({"method": "DECLINING_BALANCE"}, "annual_rate"),
        ({"code": "VAN-1"}, "code"),
    ):
        made = c.post_json(f"{base}/fixed-assets", asset_body(reg, **{"code": "X1", **bad}))
        assert made.status_code == 422, (bad, made.content)
        assert field in made.json()["errors"], made.json()

    # An unlocked asset can still be corrected.
    fixed = c.put_json(f"{base}/fixed-assets/{reg['van']['id']}", asset_body(reg, cost="24600.00"))
    assert fixed.status_code == 200 and fixed.json()["cost"] == "24600.00"  # noqa: PT018

    viewer = join(c, reg["ws"]["slug"], make_user("viewer@example.test"), api_client, "read_only")
    assert viewer.get(f"{base}/fixed-assets").status_code == 200
    assert viewer.post_json(f"{base}/fixed-assets", asset_body(reg, code="X2")).status_code == 403
    assert viewer.post_json(f"{base}/depreciation-runs",
                            {"month": "2026-02-01"}).status_code == 403  # fmt: skip
    accountant = join(c, reg["ws"]["slug"], make_user("acc@example.test"), api_client,
                      "accountant")  # fmt: skip
    assert accountant.post_json(f"{base}/depreciation-runs",
                                {"month": "2026-02-01"}).status_code == 201  # fmt: skip

    # The database keeps the history: locked terms, no deletes, run lines never change.
    set_context(tenant_id=UUID(reg["ws"]["id"]))
    asset = FixedAsset.objects.get(id=reg["van"]["id"])
    assert asset.locked_at is not None
    with pytest.raises(DatabaseError, match="locked"), transaction.atomic():
        FixedAsset.objects.filter(id=asset.id).update(cost=Decimal("1.00"))
    with pytest.raises(DatabaseError), transaction.atomic():
        FixedAsset.objects.filter(id=asset.id).delete()
    with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
        DepreciationRunLine.objects.filter(asset=asset).update(amount=Decimal("1.00"))
    # Disposal is still allowed on a locked asset (once).
    FixedAsset.objects.filter(id=asset.id).update(disposed_on=date(2026, 9, 1),
                                                  disposal_proceeds=Decimal("0"))  # fmt: skip
