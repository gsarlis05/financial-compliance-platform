"""Loans in projections (M6F-4, #149; owner decision D5). Every figure is worked out by hand in
the comments, or by the closed-form annuity formula written out independently here."""

from dataclasses import replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pytest
from django.db import DatabaseError, transaction
from hypothesis import given, settings
from hypothesis import strategies as st

from fcp.modules.calendar.api import add_months
from fcp.modules.projections import engine
from fcp.modules.projections.debt import (
    ANNUITY,
    BULLET,
    EQUAL_PRINCIPAL,
    LoanTerms,
    project_loan,
)
from fcp.modules.projections.engine import EngineInput, project
from fcp.modules.projections.models import AssumptionLoan

from ..registers.test_commitments import LOAN, post
from .test_assumptions import books, hist, make
from .test_engine import projections

pytestmark = pytest.mark.django_db
__all__ = ["books", "hist"]
D = Decimal
JAN = date(2027, 1, 1)
MONTHS = [add_months(JAN, n) for n in range(24)]


def annuity(balance: Decimal, monthly: Decimal, n: int) -> Decimal:
    """P x r / (1 - (1 + r)^-n), rounded half up to cents (independent of the engine)."""
    return (balance * monthly / (1 - (1 + monthly) ** -n)).quantize(D("0.01"), ROUND_HALF_UP)


def loan(**extra: Any) -> LoanTerms:
    base: dict[str, Any] = {"code": "L1", "structure": ANNUITY, "term_months": 12,
                            "annual_rate": D(6), "opening": D(12000)}  # fmt: skip
    return LoanTerms(**{**base, **extra})


def test_annuity() -> None:
    rows = project_loan(loan(), MONTHS[:12])
    payment = annuity(D(12000), D("0.005"), 12)  # 1,032.80
    assert payment == D("1032.80")
    # Month 1: interest 12,000 x 6% / 12 = 60.00; principal 1,032.80 - 60.00 = 972.80.
    assert (rows[0].interest, rows[0].principal, rows[0].closing) == (D(60), D("972.80"),
                                                                      D("11027.20"))  # fmt: skip
    assert rows[-1].closing == 0
    assert sum(r.principal for r in rows) == D(12000)
    for r in rows:  # each month's interest on its opening balance, and its roll-forward
        assert r.interest == (r.opening * D("0.005")).quantize(D("0.01"), ROUND_HALF_UP)
        assert r.opening - r.principal == r.closing
    # The level payment holds month after month (re-worked each month on the balance left).
    assert all(abs(r.interest + r.principal - payment) <= D("0.01") for r in rows[:-1])


def test_equal_principal_bullet_and_interest_only() -> None:
    eq = project_loan(loan(structure=EQUAL_PRINCIPAL), MONTHS[:12])
    # 12,000 / 12 = 1,000 a month; interest 60.00, then 11,000 x 0.5% = 55.00.
    assert [r.principal for r in eq] == [D(1000)] * 12
    assert (eq[0].interest, eq[1].interest) == (D(60), D(55))
    bullet = project_loan(loan(structure=BULLET), MONTHS[:12])
    assert [r.principal for r in bullet] == [D(0)] * 11 + [D(12000)]
    assert all(r.interest == D(60) for r in bullet)
    io = project_loan(loan(interest_only_months=3), MONTHS[:12])
    assert [r.principal for r in io[:3]] == [D(0)] * 3
    # Then an annuity over the 9 months left: 12,000 x 0.5% / (1 - 1.005^-9).
    assert io[3].interest + io[3].principal == annuity(D(12000), D("0.005"), 9)
    assert io[-1].closing == 0


def test_early_repayment_variable_rate_and_new_loan() -> None:
    rows = project_loan(loan(prepayments={add_months(JAN, 2): D(5000)}), MONTHS[:12])
    third = rows[2]
    assert third.prepayment == D(5000)
    assert third.closing == third.opening - third.principal - D(5000)
    # The next payment is re-worked on the lower balance over the 9 months left.
    assert rows[3].interest + rows[3].principal == annuity(third.closing, D("0.005"), 9)
    assert rows[-1].closing == 0
    capped = project_loan(loan(prepayments={JAN: D(99999)}), MONTHS[:12])
    assert capped[0].closing == 0  # an early repayment never takes more than is owed

    variable = project_loan(loan(structure=BULLET, rate_path={add_months(JAN, 3): D(9)}),
                            MONTHS[:12])  # fmt: skip
    assert [r.interest for r in variable[:5]] == [D(60)] * 3 + [D(90)] * 2  # 12,000 x 9% / 12
    assert variable[6].rate == D(9)  # the last rate holds

    new = project_loan(loan(opening=D(0), amount=D(24000), drawdown_month=add_months(JAN, 1),
                            structure=EQUAL_PRINCIPAL, term_months=24), MONTHS)  # fmt: skip
    # Drawn at the end of February: no interest in February; from March 24,000 x 0.5% = 120.00
    # and 24,000 / 24 = 1,000 a month. Current portion at the end of February: 12 x 1,000.
    assert (new[0].closing, new[1].interest, new[1].drawdown, new[1].closing) == (
        D(0), D(0), D(24000), D(24000))  # fmt: skip
    assert new[1].current == D(12000)
    assert (new[2].interest, new[2].principal) == (D(120), D(1000))


def test_engine_reconciles_loans_with_the_statements() -> None:
    opening = {"BS.CASH": D(50000), "BS.DEBT.NONCURRENT": D(15000), "BS.DEBT.CURRENT": D(3000),
               "BS.EQUITY.SHARE_CAPITAL": D(32000)}  # fmt: skip
    loans = (
        loan(),  # existing: 12,000 of the 18,000 in the books
        loan(code="L2", opening=D(0), amount=D(24000), drawdown_month=add_months(JAN, 1),
             structure=EQUAL_PRINCIPAL, term_months=24),
    )  # fmt: skip
    drivers = {("interest_rate", ""): dict.fromkeys(MONTHS, D(12))}
    inp = EngineInput("s", date(2026, 12, 31), MONTHS, opening, drivers, {}, {JAN},
                      loans=loans)  # fmt: skip
    p = project(inp)
    assert all(p.invariants.values()), {k: v for k, v in p.invariants.items() if not v}
    jan = p.months[0]
    # Interest: loan L1 60.00 + other debt (18,000 - 12,000) x 12% / 12 = 60.00.
    assert jan.pl["PL.INTEREST"] == D(120)
    assert jan.cf["CF.REPAYMENT"] == -D("972.80")
    feb = p.months[1]
    assert feb.cf["CF.BORROWING"] == D(24000)
    total = sum((r.closing for r in feb.loans.values()), D(0)) + feb.other_debt["closing"]
    assert feb.bs["BS.DEBT.CURRENT"] + feb.bs["BS.DEBT.NONCURRENT"] == total
    # A broken loan roll-forward is caught and located.
    broken = p.months[3].loans["L1"]
    p.months[3].loans["L1"] = type(broken)(**{**broken.__dict__, "closing": broken.closing + 1})
    assert engine.check(p, inp)["debt_reconciles@2027-04"] is False


def test_loans_in_a_set_and_from_the_register(hist: dict[str, Any]) -> None:
    c, base = hist["client"], hist["base"]
    s = make(hist, months=12).json()
    url = f"{base}/assumption-sets/{s['id']}/loans"
    new = {"code": "bank-2", "name": "New bank loan (Demo)", "kind": "NEW",
           "structure": "EQUAL_PRINCIPAL", "term_months": 24, "annual_rate": "6",
           "amount": "24000", "drawdown_month": "2027-02-01"}  # fmt: skip
    made = c.post_json(url, new)
    assert made.status_code == 201, made.content
    assert made.json()["code"] == "BANK-2"
    assert c.post_json(url, {**new, "drawdown_month": "2029-01-01"}).status_code == 422
    grid = c.get(f"{base}/assumption-sets/{s['id']}").json()
    rates = {(r["driver"], r["line"]): r for r in grid["rows"]}
    assert rates[("loan_rate", "BANK-2")]["values"][:2] == ["6", "6"]
    june = {"driver": "loan_prepayment", "line": "BANK-2", "month": "2027-06-01", "value": "2000"}
    early = c.put_json(f"{base}/assumption-sets/{s['id']}/values", {"changes": [june]})
    assert early.status_code == 200, early.content
    # The register's loan: 1,200 at 12% from 15/01/2026, monthly annuity to 15/01/2027; at the
    # cut-over (31/12/2026) 11 instalments are paid and one month is left.
    assert post(hist, "debt-instruments", LOAN).status_code == 201
    taken = c.post_json(f"{url}/from-register", {})
    assert taken.status_code == 201, taken.content
    (reg,) = taken.json()
    assert (reg["kind"], reg["term_months"], reg["from_register"]) == ("EXISTING", 1, True)
    sched = c.get(f"{base}/debt-instruments").json()[0]
    rows = c.get(f"{base}/debt-instruments/{sched['series_id']}/schedule").json()
    assert reg["opening_balance"] == rows[10]["closing"]
    assert c.post_json(f"{url}/from-register", {}).json() == []  # not taken twice
    # The books hold no debt, so the existing loan is refused when projecting.
    c.post_json(f"{base}/assumption-sets/{s['id']}/approve", {})
    refused = c.post_json(f"{base}/projections", {"assumption_set_id": s["id"]})
    assert refused.status_code == 422, refused.content
    assert "more than the debt in the books" in refused.json()["detail"]
    # Approved: loans no longer change (API and database).
    assert c.post_json(url, {**new, "code": "X"}).status_code == 409
    with pytest.raises(DatabaseError, match="draft"), transaction.atomic():
        AssumptionLoan.objects.filter(code="BANK-2").update(name="x")
    # A revision copies the loans; removing the register loan lets the projection run.
    v2 = c.post_json(f"{base}/assumption-sets/{s['id']}/revise", {}).json()
    url2 = f"{base}/assumption-sets/{v2['id']}/loans"
    assert [x["code"] for x in c.get(url2).json()] == ["BANK-2", reg["code"]]
    assert c.delete_json(f"{url2}/{reg['code']}").status_code == 204
    c.post_json(f"{base}/assumption-sets/{v2['id']}/approve", {})
    run = c.post_json(f"{base}/projections", {"assumption_set_id": v2["id"]}).json()
    assert run["status"] == "VALID", run
    got = c.get(f"{base}/projections/{run['id']}").json()
    assert got["rows"]["DEBT.BANK-2.drawdown"][2] == "24000.00"  # February
    assert got["rows"]["DEBT.BANK-2.prepayment"][6] == "2000.00"  # June


@st.composite
def with_loans(draw: st.DrawFn) -> EngineInput:
    base = draw(projections())
    months = base.months
    debt = base.opening["BS.DEBT.CURRENT"] + base.opening["BS.DEBT.NONCURRENT"]
    loans: list[LoanTerms] = []
    for n in range(draw(st.integers(0, 3))):
        new = draw(st.booleans())
        rate = draw(st.decimals(min_value=0, max_value=20, places=2))
        path = {m: draw(st.decimals(min_value=0, max_value=20, places=2))
                for m in months if draw(st.booleans())}  # fmt: skip
        term = draw(st.integers(1, 60))
        terms = LoanTerms(
            code=f"L{n}", structure=draw(st.sampled_from([ANNUITY, EQUAL_PRINCIPAL, BULLET])),
            term_months=term, annual_rate=rate,
            interest_only_months=draw(st.integers(0, term - 1)), rate_path=path,
            prepayments={m: draw(st.decimals(min_value=0, max_value=10**5, places=2))
                         for m in months if draw(st.booleans())},
            drawdowns={m: draw(st.decimals(min_value=0, max_value=10**4, places=2))
                       for m in months if draw(st.booleans())},
            opening=D(0) if new else draw(st.decimals(min_value=D("0.01"),
                                                      max_value=max(debt, D("0.01")), places=2)),
            amount=draw(st.decimals(min_value=D("0.01"), max_value=10**6, places=2)) if new
            else D(0),
            drawdown_month=draw(st.sampled_from(months)) if new else None,
        )  # fmt: skip
        if new or sum((x.opening for x in loans), D(0)) + terms.opening <= debt:
            loans.append(terms)
    return replace(base, loans=tuple(loans))


@settings(max_examples=120, deadline=None)
@given(with_loans())
def test_every_projection_with_loans_satisfies_the_invariants(inp: EngineInput) -> None:
    """AC-PJ1 with loans: every invariant holds exactly, debt reconciliation included."""
    p = project(inp)
    assert all(p.invariants.values()), {k: v for k, v in p.invariants.items() if not v}
