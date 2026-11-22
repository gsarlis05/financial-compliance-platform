"""VAT periods and VAT period reports (V1-2, #208): periods chosen per company and changed from
the start of a later period; a report per period from the posted ledger, worked by hand below;
sign-off (never by the preparer, except in a one-person workspace), filing recorded by hand,
versions, the settlement entry, exports and the database's rules.

Golden quarter (Q1 2026), Cyprus template accounts:
  10 Jan  sale 1,000 at S19: VAT 190                       sales 1,000 / 190
   5 Feb  sale 500 at R9: VAT 45                           sales   500 /  45
  20 Feb  purchase 400 at S19: input VAT 76                purchases 400 / 76
   1 Mar  credit note on the January sale: -100, VAT -19   sales  -100 / -19
  10 Mar  zero-rated sale 300 (Z0)                         sales   300 /   0
  15 Mar  exempt purchase 200 (EX)                         purchases 200 / 0
   2 Apr  sale 100 at S19 (next quarter, not in Q1)
Q1: sales 1,700, output VAT 216; purchases 600, input VAT 76; net VAT 140 payable.
"""

import io
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from django.db import DatabaseError, transaction
from openpyxl import load_workbook

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.tax.exports import pdf_rows
from fcp.modules.tax.models import VatPeriodScheme, VatReport
from fcp.modules.tax.periods import Scheme, periods, scheme_problem

from ..ledger.conftest import books, join

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books"]

S19, R9, Z0, EX = "CY:S19:open", "CY:R9:open", "CY:Z0:open", "CY:EX:open"
Q1 = "2026-01-01"


def post(v: dict[str, Any], day: str, *lines: tuple[str, str, str, str | None]) -> str:
    acc = v["accounts"]
    body = {"accounting_date": day, "description": f"VAT fixture {day}", "lines": [
        {"account_id": acc[code]["id"], "debit": dr, "credit": cr,
         **({"vat_code_id": vat} if vat else {})} for code, dr, cr, vat in lines]}  # fmt: skip
    made = v["client"].post_json(f"{v['base']}/journal-entries", body)
    assert made.status_code == 201, made.content
    posted = v["client"].post_json(f"{v['base']}/journal-entries/{made.json()['id']}/post", {})
    assert posted.status_code == 200, posted.content
    return str(made.json()["id"])


@pytest.fixture
def v(books: dict[str, Any]) -> dict[str, Any]:
    c, base = books["client"], books["base"]
    assert c.put_json(f"{base}/ledger-settings", {"approval_policy": "NONE"}).status_code == 200
    post(books, "2026-01-10", ("1300", "1190", "0", None), ("4000", "0", "1000", S19),
         ("2120", "0", "190", S19))  # fmt: skip
    post(books, "2026-02-05", ("1300", "545", "0", None), ("4000", "0", "500", R9),
         ("2120", "0", "45", R9))  # fmt: skip
    post(books, "2026-02-20", ("5000", "400", "0", S19), ("1220", "76", "0", S19),
         ("1300", "0", "476", None))  # fmt: skip
    post(books, "2026-03-01", ("4000", "100", "0", S19), ("2120", "19", "0", S19),
         ("1300", "0", "119", None))  # fmt: skip
    post(books, "2026-03-10", ("1300", "300", "0", None), ("4000", "0", "300", Z0))
    post(books, "2026-03-15", ("6100", "200", "0", EX), ("1300", "0", "200", None))
    post(books, "2026-04-02", ("1300", "119", "0", None), ("4000", "0", "100", S19),
         ("2120", "0", "19", S19))  # fmt: skip
    return books


def scheme(v: dict[str, Any], months: int, start: str, client: Any = None) -> Any:
    return (client or v["client"]).post_json(f"{v['base']}/vat-period-schemes",
                                             {"months": months, "effective_from": start})  # fmt: skip


def generate(v: dict[str, Any], start: str = Q1, client: Any = None) -> Any:
    return (client or v["client"]).post_json(f"{v['base']}/vat-reports", {"period_start": start})


def act(v: dict[str, Any], report_id: str, what: str, client: Any = None, **body: Any) -> Any:
    return (client or v["client"]).post_json(f"{v['base']}/vat-reports/{report_id}/{what}", body)


def test_period_rules() -> None:
    quarterly = Scheme(3, date(2026, 1, 1))
    assert scheme_problem([], Scheme(5, date(2026, 1, 1))) == (
        "A VAT period lasts 1, 2, 3, 4, 6 or 12 months."
    )
    assert scheme_problem([], Scheme(3, date(2026, 1, 15))) == (
        "VAT periods start on the first day of a month."
    )
    assert "must start where a current period would start" in str(
        scheme_problem([quarterly], Scheme(1, date(2026, 8, 1)))
    )
    assert "takes effect after the current one" in str(
        scheme_problem([quarterly], Scheme(1, date(2025, 10, 1)))
    )
    monthly = Scheme(1, date(2026, 7, 1))
    assert scheme_problem([quarterly], monthly) is None
    found = periods([quarterly, monthly], date(2026, 1, 1), date(2026, 8, 20))
    assert [(p.start.isoformat(), p.end.isoformat()) for p in found] == [
        ("2026-01-01", "2026-03-31"), ("2026-04-01", "2026-06-30"),
        ("2026-07-01", "2026-07-31"), ("2026-08-01", "2026-08-31"),
    ]  # fmt: skip
    # A period that crosses a year end, as a company's periods can.
    odd = periods([Scheme(3, date(2025, 11, 1))], date(2025, 12, 1), date(2026, 2, 1))
    assert [(p.start.isoformat(), p.end.isoformat()) for p in odd] == [
        ("2025-11-01", "2026-01-31"), ("2026-02-01", "2026-04-30"),
    ]  # fmt: skip


def test_the_golden_quarter(v: dict[str, Any]) -> None:
    assert generate(v).status_code == 422  # no VAT periods chosen yet
    made = scheme(v, 3, Q1)
    assert made.status_code == 201, made.content
    listed = v["client"].get(f"{v['base']}/vat-periods").json()
    assert listed[-1]["start"] == Q1 and listed[-1]["report"] is None
    assert generate(v, "2026-02-01").status_code == 422  # not the start of a period

    report = generate(v).json()
    snap = report["snapshot"]
    assert (report["status"], report["version"]) == ("DRAFT", 1)
    assert snap["totals"] == {"sales_base": "1700.00", "sales_vat": "216.00",
                              "purchase_base": "600.00", "purchase_vat": "76.00",
                              "net": "140.00", "direction": "PAYABLE"}  # fmt: skip
    by_code = {c["code"]: c for c in snap["codes"]}
    assert set(by_code) == {"S19", "R9", "Z0", "EX"}
    assert (by_code["S19"]["sales_base"], by_code["S19"]["sales_vat"]) == ("900.00", "171.00")
    assert (by_code["S19"]["purchase_base"], by_code["S19"]["purchase_vat"]) == ("400.00", "76.00")
    assert by_code["S19"]["sales_expected_vat"] == "171.00"
    assert (by_code["R9"]["sales_base"], by_code["R9"]["sales_vat"]) == ("500.00", "45.00")
    assert (by_code["Z0"]["sales_base"], by_code["EX"]["purchase_base"]) == ("300.00", "200.00")
    assert [(a["code"], a["role"], a["vat"]) for a in snap["accounts"]] == [
        ("1220", "INPUT", "76.00"),
        ("2120", "OUTPUT", "216.00"),
    ]
    assert snap["exceptions"] == []
    assert snap["unverified_codes"] == ["EX", "R9", "S19", "Z0"]  # verified by nobody yet (#93)
    assert snap["law"]["status"] == "AWAITING_SOURCES"
    # Every figure can be traced to its lines, and they add up.
    sales = sum(Decimal(ln["amount"]) for ln in snap["lines"] if ln["kind"] == "SALE")
    assert sales == Decimal("1700.00") and len(snap["lines"]) == 10
    assert all(ln["date"] < "2026-04-01" for ln in snap["lines"])
    assert report["blockers"] == []  # the quarter has ended and nothing changed


def test_sign_off_filing_versions_and_settlement(
    v: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    scheme(v, 3, Q1)
    report = generate(v).json()
    own = act(v, report["id"], "sign-off")
    assert own.status_code == 403  # the preparer, in a workspace of more than one is possible
    assert generate(v).status_code == 409  # one report per period
    # Posting into the period after generating blocks sign-off until regenerated.
    late = post(v, "2026-03-20", ("1300", "120", "0", None), ("4000", "0", "100", S19),
                ("2120", "0", "20", S19))  # fmt: skip
    boss = join(v["client"], v["ws"]["slug"], make_user("fm@example.test"), api_client,
                "finance_manager")  # fmt: skip
    stale = act(v, report["id"], "sign-off", boss)
    assert stale.status_code == 409
    assert stale.json()["code"] == "tax.vat.not_signable"
    assert "Regenerate it" in stale.json()["detail"]
    again = act(v, report["id"], "regenerate").json()
    assert again["snapshot"]["totals"]["sales_vat"] == "236.00"
    kinds = [e["kind"] for e in again["snapshot"]["exceptions"]]
    assert kinds == ["RATE_MISMATCH"]  # 20 recorded on 100 at 19%: one euro too much
    assert (
        "S19 (sales): VAT recorded 191.00, 190.00" in again["snapshot"]["exceptions"][0]["detail"]
    )
    # The owner corrects it by reversal, regenerates and the manager signs off.
    rev = v["client"].post_json(f"{v['base']}/journal-entries/{late}/reverse",
                                {"reason": "Wrong VAT amount",
                                 "reversal_date": "2026-03-20"}).json()  # fmt: skip
    reversed_ = v["client"].post_json(f"{v['base']}/journal-entries/{rev['id']}/post", {})
    assert reversed_.status_code == 200, reversed_.content
    act(v, report["id"], "regenerate")
    signed = act(v, report["id"], "sign-off", boss)
    assert signed.status_code == 200, signed.content
    body = signed.json()
    assert (body["status"], body["self_approved"]) == ("SIGNED_OFF", False)
    assert body["snapshot"]["totals"]["net"] == "140.00"
    assert act(v, report["id"], "regenerate").status_code == 409  # frozen

    # The settlement entry moves the input VAT into the output VAT account, as a draft.
    settled = act(v, report["id"], "settlement")
    assert settled.status_code == 201, settled.content
    entry = v["client"].get(f"{v['base']}/journal-entries/{settled.json()['entry_id']}").json()
    assert (entry["status"], entry["accounting_date"]) == ("DRAFT", "2026-03-31")
    assert sorted((ln["debit"], ln["credit"]) for ln in entry["lines"]) == [
        ("0.00", "76.00"),
        ("76.00", "0.00"),
    ]
    assert act(v, report["id"], "settlement").status_code == 409  # once only

    # Filing is recorded by hand with the portal's reference; nothing is sent anywhere.
    assert act(v, report["id"], "filed", boss, filed_on="2026-05-05",
               reference=" ").status_code == 422  # fmt: skip
    filed = act(v, report["id"], "filed", boss, filed_on="2026-05-05", reference="TAXIS-123")
    assert filed.status_code == 200, filed.content
    assert (filed.json()["status"], filed.json()["filing_reference"]) == ("FILED", "TAXIS-123")

    # A correction is a new version; signing it off supersedes the filed one.
    v2 = act(v, report["id"], "new-version")
    assert v2.status_code == 201, v2.content
    assert (v2.json()["version"], v2.json()["supersedes_id"]) == (2, report["id"])
    assert act(v, report["id"], "new-version").status_code == 409
    assert act(v, v2.json()["id"], "sign-off", boss).status_code == 200
    first = v["client"].get(f"{v['base']}/vat-reports/{report['id']}").json()
    assert first["status"] == "SUPERSEDED"
    listed = v["client"].get(f"{v['base']}/vat-periods").json()
    assert next(p for p in listed if p["start"] == Q1)["report"]["version"] == 2

    set_context(tenant_id=UUID(v["ws"]["id"]))
    actions = [e.action for e in AuditEvent.objects.filter(action__startswith="tax.vat.")]
    for action in ("tax.vat.periods_set", "tax.vat.report_generated", "tax.vat.report_signed_off",
                   "tax.vat.settlement_prepared", "tax.vat.report_filed",
                   "tax.vat.report_superseded"):  # fmt: skip
        assert action in actions


def test_one_person_self_sign_off_and_rules(v: dict[str, Any]) -> None:
    scheme(v, 3, Q1)
    # A period that has not ended cannot be signed off.
    assert scheme(v, 3, "2026-10-01").status_code == 201  # same length, from Q4: allowed
    q4 = generate(v, "2026-10-01").json()
    assert "ends on 2026-12-31" in q4["blockers"][0]
    report = generate(v).json()
    slug = v["ws"]["slug"]
    assert v["client"].put_json(f"/api/w/{slug}/one-person", {"enabled": True}).status_code == 200
    signed = act(v, report["id"], "sign-off")
    assert signed.status_code == 200, signed.content
    assert signed.json()["self_approved"] is True
    # Periods cannot change under a signed-off report.
    refused = scheme(v, 1, "2026-01-01")
    assert refused.status_code == 422


def test_database_rules(v: dict[str, Any]) -> None:
    scheme(v, 3, Q1)
    report = generate(v).json()
    set_context(tenant_id=UUID(v["ws"]["id"]))
    with pytest.raises(DatabaseError, match="never changes"), transaction.atomic():
        VatPeriodScheme.objects.update(months=1)
    with pytest.raises(DatabaseError, match="VAT reports are kept"), transaction.atomic():
        VatReport.objects.filter(id=report["id"]).delete()
    with pytest.raises(DatabaseError, match="cannot be its preparer"), transaction.atomic():
        VatReport.objects.filter(id=report["id"]).update(
            status="SIGNED_OFF", signed_off_by=v["owner"], signed_off_at="2026-04-02T00:00Z"
        )
    VatReport.objects.filter(id=report["id"]).update(snapshot={"forged": True})  # a draft may
    act(v, report["id"], "regenerate")


def test_exports_and_permissions(v: dict[str, Any], make_user: Make, api_client: Make) -> None:
    scheme(v, 3, Q1)
    report = generate(v).json()
    url = f"{v['base']}/vat-reports/{report['id']}/export"
    xlsx = v["client"].get(f"{url}?format=xlsx")
    assert xlsx.status_code == 200
    assert xlsx["Content-Disposition"].endswith('vat-report-2026-01-2026-03-v1-draft.xlsx"')
    book = load_workbook(io.BytesIO(xlsx.content))
    codes = [list(r) for r in book["Codes"].iter_rows(values_only=True)]
    shown = {c["code"]: c for c in report["snapshot"]["codes"]}
    for row in codes[1:]:
        assert Decimal(str(row[2])) == Decimal(shown[str(row[0])]["sales_base"])
        assert Decimal(str(row[3])) == Decimal(shown[str(row[0])]["sales_vat"])
    summary = [list(r) for r in book["VAT"].iter_rows(values_only=True)]
    assert ["Net VAT (payable)", Decimal("140")] in [[r[0], r[1]] for r in summary
                                                      if r[1] is not None]  # fmt: skip
    pdf = v["client"].get(f"{url}?format=pdf&lang=el")
    assert (pdf.status_code, pdf["Content-Type"]) == (200, "application/pdf")
    set_context(tenant_id=UUID(v["ws"]["id"]))
    rows = pdf_rows(VatReport.objects.get(id=report["id"]), "el")
    assert rows[1:] == [[c["code"], c["rate"] or "", *[
        f"{Decimal(c[k]):,.2f}".translate(str.maketrans(",.", ".,"))
        for k in ("sales_base", "sales_vat", "purchase_base", "purchase_vat")]]
        for c in report["snapshot"]["codes"]]  # fmt: skip

    viewer = join(v["client"], v["ws"]["slug"], make_user("ro@example.test"), api_client,
                  "read_only")  # fmt: skip
    assert viewer.get(f"{v['base']}/vat-reports/{report['id']}").status_code == 200
    assert generate(v, client=viewer).status_code == 403
    assert scheme(v, 1, "2026-04-01", client=viewer).status_code == 403
    assert viewer.get(f"{url}?format=pdf").status_code == 403  # needs reports.export
