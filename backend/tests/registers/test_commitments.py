"""Recurring obligations, loans, facilities and holidays (M3-4)."""

from collections.abc import Callable
from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest
from django.db import DatabaseError, transaction

from fcp.core.db.rls import set_context
from fcp.modules.registers.models import DebtInstrument, RecurringObligation

from ..ledger.conftest import books, join

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books"]

RENT = {
    "name": "Office rent",
    "category": "RENT",
    "direction": "OUTFLOW",
    "amount": "1500.00",
    "frequency": "MONTHLY",
    "day_of_month": 1,
    "start_date": "2026-01-01",
    "adjust": "FOLLOWING",
    "contractual": True,
}
LOAN = {
    "name": "Term loan",
    "kind": "TERM_LOAN",
    "principal": "1200.00",
    "start_date": "2026-01-15",
    "maturity_date": "2027-01-15",
    "rate_type": "FIXED",
    "fixed_rate": "0.12",
    "day_count": "30_360",
    "repayment_type": "ANNUITY",
    "adjust": "NONE",
}


@pytest.fixture
def cm(books: dict[str, Any]) -> dict[str, Any]:
    return books


def post(cm: dict[str, Any], path: str, body: dict[str, Any], client: Any = None) -> Any:
    return (client or cm["client"]).post_json(f"{cm['base']}/{path}", body)


def test_obligation_versions_keep_history(cm: dict[str, Any]) -> None:
    created = post(cm, "obligations", RENT)
    assert created.status_code == 201, created.content
    first = created.json()
    assert (first["version"], first["nature"], first["amount"]) == (1, "COMMITTED", "1500.00")
    series = first["series_id"]
    changed = cm["client"].put_json(
        f"{cm['base']}/obligations/{series}", {**RENT, "amount": "1600.00", "contractual": False}
    )
    assert changed.status_code == 200, changed.content
    assert (changed.json()["version"], changed.json()["nature"]) == (2, "EXPECTED")
    listed = cm["client"].get(f"{cm['base']}/obligations").json()
    assert [(o["series_id"], o["amount"]) for o in listed] == [(series, "1600.00")]
    history = cm["client"].get(f"{cm['base']}/obligations/{series}/history").json()
    assert [h["version"] for h in history] == [1, 2]
    assert history[0]["superseded_at"] is not None
    assert history[1]["superseded_at"] is None
    retired = post(cm, f"obligations/{series}/retire", {})
    assert retired.status_code == 200
    assert cm["client"].get(f"{cm['base']}/obligations").json() == []
    again = post(cm, f"obligations/{series}/retire", {})
    assert again.status_code == 404
    missing = cm["client"].put_json(f"{cm['base']}/obligations/{uuid4()}", RENT)
    assert missing.status_code == 404
    assert cm["client"].get(f"{cm['base']}/obligations/{uuid4()}/history").status_code == 404


def test_versions_are_immutable_in_the_database(cm: dict[str, Any]) -> None:
    obligation = post(cm, "obligations", RENT).json()
    loan = post(cm, "debt-instruments", LOAN).json()
    with transaction.atomic():
        set_context(tenant_id=cm["ws"]["id"])
        for model, row in ((RecurringObligation, obligation), (DebtInstrument, loan)):
            with pytest.raises(DatabaseError, match="immutable"), transaction.atomic():
                model.objects.filter(id=row["id"]).update(name="Changed")
            with pytest.raises(DatabaseError, match="retire instead"), transaction.atomic():
                model.objects.filter(id=row["id"]).delete()


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"amount": "0.00"}, "amount"),
        ({"interval": 0}, None),
        ({"end_date": "2025-01-01"}, "schedule"),
        ({"frequency": "WEEKLY"}, "schedule"),  # weekly with a day of the month
        ({"counterparty_id": str(uuid4())}, "counterparty_id"),
    ],
)
def test_obligation_validation(
    cm: dict[str, Any], changes: dict[str, Any], field: str | None
) -> None:
    response = post(cm, "obligations", {**RENT, **changes})
    assert response.status_code == 422, response.content
    if field:
        assert field in response.json()["errors"]


def test_loan_schedule_and_flows(cm: dict[str, Any]) -> None:
    loan = post(cm, "debt-instruments", LOAN)
    assert loan.status_code == 201, loan.content
    series = loan.json()["series_id"]
    rows = cm["client"].get(f"{cm['base']}/debt-instruments/{series}/schedule").json()
    assert len(rows) == 12
    assert (rows[0]["interest"], rows[0]["principal"], rows[0]["payment"]) == (
        "12.00",
        "94.62",
        "106.62",
    )
    assert rows[-1]["closing"] == "0.00"
    post(cm, "obligations", RENT)
    flows = (
        cm["client"]
        .get(f"{cm['base']}/commitment-flows", {"date_from": "2026-02-01", "date_to": "2026-02-28"})
        .json()
    )
    assert [(f["due"], f["source"], f["component"], f["amount"], f["nature"]) for f in flows] == [
        ("2026-02-02", "OBLIGATION", "PAYMENT", "-1500.00", "COMMITTED"),  # 1 Feb is a Sunday
        ("2026-02-15", "DEBT", "INTEREST", "-12.00", "COMMITTED"),
        ("2026-02-15", "DEBT", "PRINCIPAL", "-94.62", "COMMITTED"),
    ]
    assert flows[1]["version_id"] == loan.json()["id"]
    too_long = cm["client"].get(
        f"{cm['base']}/commitment-flows", {"date_from": "2026-01-01", "date_to": "2030-01-01"}
    )
    assert too_long.status_code == 422


def test_variable_rate_interest_is_expected(cm: dict[str, Any]) -> None:
    variable = {
        **LOAN,
        "rate_type": "VARIABLE",
        "fixed_rate": None,
        "reference_rate_key": "EURIBOR_3M",
        "margin": "0.02",
        "assumed_reference_rate": "0.10",
    }
    created = post(cm, "debt-instruments", variable)
    assert created.status_code == 201, created.content
    flows = (
        cm["client"]
        .get(f"{cm['base']}/commitment-flows", {"date_from": "2026-02-01", "date_to": "2026-02-28"})
        .json()
    )
    natures = {f["component"]: (f["nature"], f["amount"]) for f in flows}
    assert natures == {"INTEREST": ("EXPECTED", "-12.00"), "PRINCIPAL": ("COMMITTED", "-94.62")}
    missing = post(cm, "debt-instruments", {**variable, "reference_rate_key": ""})
    assert "reference_rate_key" in missing.json()["errors"]
    no_margin = post(cm, "debt-instruments", {**variable, "margin": None})
    assert "margin" in no_margin.json()["errors"]


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"fixed_rate": None}, "fixed_rate"),
        ({"maturity_date": "2026-12-20"}, "schedule"),
        ({"repayment_type": ""}, "repayment_type"),
        ({"principal": None}, "principal"),
        ({"lender_id": str(uuid4())}, "lender_id"),
        ({"kind": "OVERDRAFT", "facility_limit": "5000.00"}, "principal"),
    ],
)
def test_loan_validation(cm: dict[str, Any], changes: dict[str, Any], field: str) -> None:
    response = post(cm, "debt-instruments", {**LOAN, **changes})
    assert response.status_code == 422, response.content
    assert field in response.json()["errors"]


def test_facilities_have_a_limit_and_no_flows(cm: dict[str, Any]) -> None:
    facility = {
        "name": "Overdraft",
        "kind": "OVERDRAFT",
        "facility_limit": "20000.00",
        "start_date": "2026-01-01",
        "rate_type": "FIXED",
        "fixed_rate": "0.08",
    }
    created = post(cm, "debt-instruments", facility)
    assert created.status_code == 201, created.content
    series = created.json()["series_id"]
    assert cm["client"].get(f"{cm['base']}/debt-instruments/{series}/schedule").json() == []
    flows = (
        cm["client"]
        .get(f"{cm['base']}/commitment-flows", {"date_from": "2026-01-01", "date_to": "2026-12-31"})
        .json()
    )
    assert flows == []
    no_limit = post(cm, "debt-instruments", {**facility, "facility_limit": None})
    assert "facility_limit" in no_limit.json()["errors"]
    changed = cm["client"].put_json(
        f"{cm['base']}/debt-instruments/{series}", {**facility, "facility_limit": "25000.00"}
    )
    assert changed.json()["version"] == 2
    history = cm["client"].get(f"{cm['base']}/debt-instruments/{series}/history").json()
    assert [h["facility_limit"] for h in history] == ["20000.00", "25000.00"]
    assert post(cm, f"debt-instruments/{series}/retire", {}).status_code == 200
    assert cm["client"].get(f"{cm['base']}/debt-instruments").json() == []


def test_holidays_move_payments(cm: dict[str, Any]) -> None:
    post(cm, "obligations", RENT)
    holiday = post(cm, "holidays", {"day": "2026-06-01", "name": "Synthetic holiday"})
    assert holiday.status_code == 201, holiday.content
    assert post(cm, "holidays", {"day": "2026-06-01", "name": "Again"}).status_code == 409
    flows = (
        cm["client"]
        .get(f"{cm['base']}/commitment-flows", {"date_from": "2026-06-01", "date_to": "2026-06-30"})
        .json()
    )
    assert [f["due"] for f in flows] == ["2026-06-02"]
    assert [h["day"] for h in cm["client"].get(f"{cm['base']}/holidays").json()] == ["2026-06-01"]
    removed = cm["client"].delete_json(f"{cm['base']}/holidays/{holiday.json()['id']}")
    assert removed.status_code == 204
    flows = (
        cm["client"]
        .get(f"{cm['base']}/commitment-flows", {"date_from": "2026-06-01", "date_to": "2026-06-30"})
        .json()
    )
    assert [f["due"] for f in flows] == ["2026-06-01"]
    assert cm["client"].delete_json(f"{cm['base']}/holidays/{uuid4()}").status_code == 404


def test_counterparty_links_stay_in_the_entity(cm: dict[str, Any]) -> None:
    lender = post(
        cm, "counterparties", {"code": "BANK1", "name": "Synthetic Bank", "kind": "LENDER"}
    )
    assert lender.status_code == 201, lender.content
    created = post(cm, "debt-instruments", {**LOAN, "lender_id": lender.json()["id"]})
    assert created.status_code == 201, created.content
    assert created.json()["lender_id"] == lender.json()["id"]


def test_permissions_and_isolation(
    cm: dict[str, Any], make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    post(cm, "obligations", RENT)
    viewer = join(
        cm["client"], cm["ws"]["slug"], make_user("ro@example.test"), api_client, "read_only"
    )
    assert viewer.get(f"{cm['base']}/obligations").status_code == 200
    assert post(cm, "obligations", RENT, client=viewer).status_code == 403
    assert (
        post(cm, "holidays", {"day": "2026-01-06", "name": "x"}, client=viewer).status_code == 403
    )
    stranger = make_user("stranger@example.test")
    ws = make_workspace(stranger, name="Other Ltd")
    other = api_client(stranger)
    assert other.get(f"{cm['base']}/obligations").status_code == 404
    entity = other.get(f"/api/w/{ws['slug']}/entities").json()[0]
    assert other.get(f"/api/w/{ws['slug']}/entities/{entity['id']}/obligations").json() == []


def test_service_level_checks_and_facilities(cm: dict[str, Any]) -> None:
    """Checks the HTTP schema already makes, repeated in the service for other callers."""
    from datetime import date  # noqa: PLC0415
    from decimal import Decimal  # noqa: PLC0415

    from fcp.core.errors import ValidationFailedError  # noqa: PLC0415
    from fcp.modules.registers import commitments  # noqa: PLC0415
    from fcp.modules.registers.api import facilities  # noqa: PLC0415
    from fcp.modules.tenancy import services as tenancy  # noqa: PLC0415

    entity = cm["entity"]["id"]
    with transaction.atomic():
        ctx = tenancy.enter_workspace(cm["owner"], cm["ws"]["slug"])
        rent = commitments.ObligationInput(
            "Rent",
            "RENT",
            "OUTFLOW",
            Decimal("10.00"),
            "MONTHLY",
            date(2026, 1, 1),
            contractual=True,
        )
        loan = commitments.DebtInput(
            "Loan",
            "TERM_LOAN",
            date(2026, 1, 15),
            "FIXED",
            "30_360",
            principal=Decimal("100.00"),
            maturity_date=date(2027, 1, 15),
            fixed_rate=Decimal("0.05"),
            repayment_type="ANNUITY",
        )
        for bad, field in (
            (replace(rent, category="X"), "category"),
            (replace(rent, direction="X"), "direction"),
        ):
            with pytest.raises(ValidationFailedError) as caught:
                commitments.save_obligation(ctx, entity, bad)
            assert field in caught.value.field_errors
        for bad_loan, field in (
            (replace(loan, kind="X"), "kind"),
            (replace(loan, rate_type="X"), "rate_type"),
            (replace(loan, day_count="X"), "day_count"),
        ):
            with pytest.raises(ValidationFailedError) as caught:
                commitments.save_debt(ctx, entity, bad_loan)
            assert field in caught.value.field_errors
        commitments.save_debt(
            ctx,
            entity,
            replace(
                loan,
                kind="REVOLVER",
                principal=None,
                maturity_date=None,
                repayment_type="",
                facility_limit=Decimal("5000.00"),
            ),
        )
        commitments.save_debt(ctx, entity, loan)
        assert [f.facility_limit for f in facilities(ctx, entity)] == [Decimal("5000.00")]
