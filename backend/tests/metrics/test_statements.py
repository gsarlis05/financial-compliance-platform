"""Basic statements: P&L, balance sheet, indirect cash flow (M2-8, AC-M2-8)."""

import csv
import io
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from openpyxl import load_workbook

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.metrics.models import TaxonomyLine
from fcp.modules.metrics.statements import (
    CASH_FLOW_RULES,
    LABELS,
    PL_LAYOUT,
    Period,
    prior_year,
)
from fcp.modules.metrics.taxonomy import DEFAULT_TAXONOMY

from ..ledger.conftest import books, join
from ..ledger.test_dimensions import commit_point
from .test_mapping import defaults, mb, post

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books", "mb"]


def statements(
    mb: dict[str, Any], date_from: str = "2026-01-01", date_to: str = "2026-12-31", **params: str
) -> Any:
    return mb["client"].get(
        f"{mb['base']}/statements", {"date_from": date_from, "date_to": date_to, **params}
    )


def ok(mb: dict[str, Any], *args: str, **params: str) -> dict[str, Any]:
    response = statements(mb, *args, **params)
    assert response.status_code == 200, response.content
    result: dict[str, Any] = response.json()
    assert result["ok"] is True, [
        c
        for s in ("profit_and_loss", "balance_sheet", "cash_flow")
        for c in result[s]["checks"]
        if not c["ok"]
    ]
    return result


def amounts(statement: dict[str, Any], column: str = "current") -> dict[str, str | None]:
    return {r["code"]: r[column] for r in statement["rows"] if r["kind"] != "heading"}


@pytest.fixture
def two_years(mb: dict[str, Any]) -> dict[str, Any]:
    """FY2025 and FY2026 of a small company (see the expected figures in the tests)."""
    fy = mb["client"].post_json(f"{mb['base']}/fiscal-years", {"start_date": "2025-01-01"})
    assert fy.status_code == 201, fy.content
    defaults(mb)
    for day, debit, credit, amount in [
        ("2025-01-02", "1300", "3000", "10000.00"),  # share capital paid in
        ("2025-06-30", "1300", "4000", "5000.00"),  # cash sales
        ("2025-07-01", "6100", "1300", "1000.00"),  # rent
        ("2026-02-01", "1010", "1300", "3000.00"),  # equipment bought
        ("2026-03-01", "1300", "2010", "4000.00"),  # bank loan drawn
        ("2026-04-15", "1210", "4100", "2000.00"),  # services invoiced, not yet paid
        ("2026-05-31", "6000", "1300", "2500.00"),  # payroll
        ("2026-06-30", "1300", "4000", "7000.00"),  # cash sales
        ("2026-09-30", "7000", "1300", "50.00"),  # loan interest
        ("2026-12-31", "6600", "1019", "600.00"),  # depreciation
        ("2026-12-31", "6900", "2110", "300.00"),  # accrued expense
    ]:
        post(mb, (debit, amount, "0"), (credit, "0", amount), day=day)
    commit_point()  # run the deferred posting checks now, under this tenant's context
    return mb


def test_unmapped_accounts_with_a_balance_block_statements(mb: dict[str, Any]) -> None:
    post(mb, ("6100", "100.00", "0"), ("1300", "0", "100.00"))
    blocked = statements(mb)
    assert blocked.status_code == 409
    problem = blocked.json()
    assert problem["code"] == "metrics.statements.mapping_incomplete"
    assert set(problem["errors"]) == {"1300", "6100"}
    assert problem["errors"]["1300"] == ["unmapped and has a balance on 2026-12-31"]
    defaults(mb)
    ok(mb)


def test_profit_and_loss_with_subtotals_and_comparatives(two_years: dict[str, Any]) -> None:
    pl = ok(two_years)["profit_and_loss"]
    now, before = amounts(pl), amounts(pl, "comparative")
    assert now["REV.SALES"] == "7000.00"
    assert now["REV.SERVICES"] == "2000.00"
    assert now["PL.GROSS_PROFIT"] == "9000.00"
    assert now["OPEX.PAYROLL"] == "-2500.00"
    assert now["PL.EBITDA"] == "6200.00"
    assert now["PL.OPERATING_PROFIT"] == "5600.00"
    assert now["PL.PROFIT_BEFORE_TAX"] == "5550.00"
    assert now["PL.RESULT"] == "5550.00"
    assert before["REV.SALES"] == "5000.00"
    assert before["OPEX.RENT"] == "-1000.00"
    assert before["PL.RESULT"] == "4000.00"
    assert now["OPEX.RENT"] == "0.00"  # shown: it has a comparative
    # P&L result = movement in equity, less contributions (AC-M2-8).
    check = {(c["code"], c["column"]): c for c in pl["checks"]}
    current = check[("result_equals_equity_movement", "current")]["values"]
    assert current == {
        "result": "5550.00",
        "equity_opening": "14000.00",
        "equity_closing": "19550.00",
        "contributions_and_distributions": "0.00",
    }
    prior = check[("result_equals_equity_movement", "comparative")]["values"]
    assert prior["contributions_and_distributions"] == "10000.00"
    assert prior["result"] == "4000.00"


def test_balance_sheet_balances_with_the_result_in_equity(two_years: dict[str, Any]) -> None:
    bs = ok(two_years)["balance_sheet"]
    now, before = amounts(bs), amounts(bs, "comparative")
    assert now["BS.PPE.GROSS"] == "3000.00"
    assert now["BS.PPE.ACCDEP"] == "-600.00"
    assert now["BS.TOTAL.NON_CURRENT_ASSETS"] == "2400.00"
    assert now["BS.CASH"] == "19450.00"
    assert now["BS.TOTAL_ASSETS"] == "23850.00"
    assert now["BS.EQUITY.SHARE_CAPITAL"] == "10000.00"
    assert now["BS.EQUITY.RESULT_YTD"] == "5550.00"
    assert now["BS.EQUITY.PRIOR_UNCLOSED"] == "4000.00"  # FY2025 not closed yet (M2-9)
    assert now["BS.TOTAL.EQUITY"] == "19550.00"
    assert now["BS.TOTAL_LIABILITIES"] == "4300.00"
    assert now["BS.TOTAL_EQUITY_LIABILITIES"] == "23850.00"
    assert before["BS.TOTAL_ASSETS"] == before["BS.TOTAL_EQUITY_LIABILITIES"] == "14000.00"
    assert before["BS.EQUITY.RESULT_YTD"] == "4000.00"
    assert {c["code"] for c in bs["checks"]} == {
        "balance_sheet_balances",
        "equity_matches_accounts",
    }


def test_cash_flow_reconciles_to_the_movement_in_cash(two_years: dict[str, Any]) -> None:
    cf = ok(two_years)["cash_flow"]
    now, before = amounts(cf), amounts(cf, "comparative")
    assert now["CF.RESULT"] == "5550.00"
    assert now["CF.NONCASH"] == "600.00"
    assert now["CF.BS.OTHER_REC"] == "-2000.00"
    assert now["CF.BS.OTHER_PAY"] == "300.00"
    assert now["CF.TOTAL.OPERATING"] == "4450.00"
    assert now["CF.INV.PPE"] == "-3000.00"  # the purchase, not the net book value movement
    assert now["CF.TOTAL.INVESTING"] == "-3000.00"
    assert now["CF.BS.DEBT.NONCURRENT"] == "4000.00"
    assert now["CF.NET_CHANGE"] == "5450.00"
    assert now["CF.CASH_OPENING"] == "14000.00"
    assert now["CF.CASH_CLOSING"] == "19450.00"
    assert before["CF.BS.EQUITY.SHARE_CAPITAL"] == "10000.00"
    assert before["CF.NET_CHANGE"] == before["CF.CASH_CLOSING"] == "14000.00"
    ppe = next(r for r in cf["rows"] if r["code"] == "CF.INV.PPE")
    assert [(a["code"], a["current"]) for a in ppe["accounts"]] == [
        ("1010", "-3000.00"),
        ("1019", "600.00"),
        ("", "-600.00"),
    ]


def test_drill_down_lists_accounts_per_line(two_years: dict[str, Any]) -> None:
    bs = ok(two_years)["balance_sheet"]
    cash = next(r for r in bs["rows"] if r["code"] == "BS.CASH")
    assert [(a["code"], a["current"], a["comparative"]) for a in cash["accounts"]] == [
        ("1300", "19450.00", "14000.00")
    ]
    assert cash["accounts"][0]["account_id"] == two_years["accounts"]["1300"]["id"]


def test_a_period_within_the_year(two_years: dict[str, Any]) -> None:
    result = ok(two_years, "2026-04-01", "2026-06-30", comparative="none")
    assert result["comparative_from"] is None
    pl, bs, cf = (amounts(result[k]) for k in ("profit_and_loss", "balance_sheet", "cash_flow"))
    assert pl["PL.RESULT"] == "6500.00"  # 2000 + 7000 - 2500
    assert bs["BS.EQUITY.RESULT_YTD"] == "6500.00"
    assert cf["CF.CASH_OPENING"] == "15000.00"  # 14000 - 3000 + 4000
    assert cf["CF.CASH_CLOSING"] == "19500.00"
    assert all(r["comparative"] is None for r in result["balance_sheet"]["rows"])


def test_period_validation_and_missing_fiscal_years(mb: dict[str, Any]) -> None:
    assert statements(mb, "2026-12-31", "2026-01-01").status_code == 422
    defaults(mb)
    # Before the first fiscal year, years are extended backwards (2025 here).
    assert ok(mb, "2024-03-01", "2024-03-31")["date_to"] == "2024-03-31"


def test_prior_year_handles_leap_days() -> None:
    assert prior_year(Period(date(2024, 2, 29), date(2024, 2, 29))) == Period(
        date(2023, 2, 28), date(2023, 2, 28)
    )


def test_layout_and_cash_flow_rules_cover_the_taxonomy(reference_data: None) -> None:
    del reference_data
    lines = list(TaxonomyLine.objects.filter(version_id=DEFAULT_TAXONOMY))
    rules = CASH_FLOW_RULES[DEFAULT_TAXONOMY]
    balance_sheet = sorted(ln.code for ln in lines if ln.statement == "BS")
    assert sorted(rules.classified()) == balance_sheet  # each line exactly once
    sections = {ln.section for ln in lines if ln.statement == "PL"}
    assert sections == {section for section, _ in PL_LAYOUT}
    groups = {group for group, _, _ in rules.investing}
    assert set(rules.noncash.values()) <= groups
    assert set(rules.noncash) <= {ln.code for ln in lines if ln.statement == "PL"}
    assert {ln.section for ln in lines if ln.statement == "BS"} <= set(LABELS)


def test_exports_are_audited_and_formula_safe(two_years: dict[str, Any]) -> None:
    base, client = two_years["base"], two_years["client"]
    query = {"date_from": "2026-01-01", "date_to": "2026-12-31"}
    exported = client.get(f"{base}/statements/export", {**query, "format": "csv"})
    assert exported.status_code == 200
    assert exported["Content-Disposition"] == (
        'attachment; filename="statements-2026-01-01-2026-12-31.csv"'
    )
    rows = list(csv.reader(io.StringIO(exported.content.decode())))
    assert rows[0][:4] == ["Statement", "Kind", "Code", "Row"]
    assert [
        "PL",
        "total",
        "PL.RESULT",
        "Profit (loss) for the period",
        "5550.00",
        "4000.00",
    ] in rows

    greek = client.get(f"{base}/statements/export", {**query, "format": "csv", "lang": "el"})
    assert "Κέρδος (ζημιά) περιόδου" in greek.content.decode()

    xlsx = client.get(f"{base}/statements/export", {**query, "format": "xlsx"})
    book = load_workbook(io.BytesIO(xlsx.content))
    assert book.sheetnames == ["PL", "BS", "CF"]
    values = {r[0]: r[1:] for r in book["BS"].iter_rows(min_row=6, values_only=True)}
    assert values["Total assets"] == (Decimal("23850.00"), Decimal("14000.00"))

    for lang in ("en", "el"):
        pdf = client.get(f"{base}/statements/export", {**query, "format": "pdf", "lang": lang})
        assert pdf.status_code == 200
        assert pdf["Content-Type"] == "application/pdf"
        assert pdf.content.startswith(b"%PDF")

    set_context(tenant_id=two_years["ws"]["id"])
    events = AuditEvent.objects.filter(action="reports.exported", subject_id="statements")
    assert sorted(e.changes["format"] for e in events) == ["csv", "csv", "pdf", "pdf", "xlsx"]


def test_read_only_users_read_but_do_not_export(
    two_years: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    viewer = join(
        two_years["client"],
        two_years["ws"]["slug"],
        make_user("ro@example.test"),
        api_client,
        "read_only",
    )
    base = two_years["base"]
    query = {"date_from": "2026-01-01", "date_to": "2026-12-31"}
    assert viewer.get(f"{base}/statements", query).status_code == 200
    assert viewer.get(f"{base}/statements/export", {**query, "format": "csv"}).status_code == 403


def test_other_workspaces_cannot_read_statements(
    two_years: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    stranger = api_client(make_user("stranger@example.test"))
    response = stranger.get(
        f"{two_years['base']}/statements", {"date_from": "2026-01-01", "date_to": "2026-12-31"}
    )
    assert response.status_code == 404


# Property: whatever is posted, every check holds for any period (AC-M2-8).
PAIRS = [
    ("6100", "1300"),
    ("1300", "4000"),
    ("6900", "2110"),
    ("1010", "1300"),
    ("6600", "1019"),
    ("1300", "2010"),
    ("1210", "4100"),
    ("1300", "3000"),
    ("2010", "1300"),
    ("1300", "1210"),
    ("3200", "1300"),
    ("7000", "1300"),
]
postings = st.lists(
    st.tuples(
        st.dates(min_value=date(2025, 1, 1), max_value=date(2026, 12, 31)),
        st.sampled_from(PAIRS),
        st.decimals(min_value=Decimal("0.01"), max_value=Decimal("99999.99"), places=2),
    ),
    min_size=1,
    max_size=8,
)


@settings(
    max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    entries=postings,
    start=st.dates(min_value=date(2025, 1, 1), max_value=date(2026, 12, 31)),
    days=st.integers(min_value=0, max_value=500),
)
def test_every_check_holds_for_any_postings_and_period(
    two_years: dict[str, Any], entries: list[Any], start: date, days: int
) -> None:
    for day, (debit, credit), amount in entries:
        post(
            two_years,
            (debit, f"{amount:.2f}", "0"),
            (credit, "0", f"{amount:.2f}"),
            day=day.isoformat(),
        )
    commit_point()
    end = min(date.fromordinal(start.toordinal() + days), date(2026, 12, 31))
    result = ok(two_years, start.isoformat(), end.isoformat())
    bs = amounts(result["balance_sheet"])
    assert bs["BS.TOTAL_ASSETS"] == bs["BS.TOTAL_EQUITY_LIABILITIES"]


def test_years_after_the_last_fiscal_year_carry_the_unclosed_result(mb: dict[str, Any]) -> None:
    defaults(mb)
    post(mb, ("6100", "100.00", "0"), ("1300", "0", "100.00"))
    commit_point()
    bs = amounts(ok(mb, "2028-01-01", "2028-03-31")["balance_sheet"])
    assert bs["BS.EQUITY.RESULT_YTD"] == "0.00"  # fiscal year 2028 is derived from 2026
    assert bs["BS.EQUITY.PRIOR_UNCLOSED"] == "-100.00"
    assert bs["BS.TOTAL_ASSETS"] == bs["BS.TOTAL_EQUITY_LIABILITIES"] == "-100.00"


def test_statements_need_a_fiscal_year(make_user: Make, api_client: Make,
                                       make_workspace: Make) -> None:  # fmt: skip
    owner = make_user("nofy@example.test")
    ws = make_workspace(owner, name="No Years")
    client = api_client(owner)
    entity = client.get(f"/api/w/{ws['slug']}/entities").json()[0]
    response = client.get(f"/api/w/{ws['slug']}/entities/{entity['id']}/statements",
                          {"date_from": "2026-01-01", "date_to": "2026-12-31"})  # fmt: skip
    assert response.status_code == 422
    assert response.json()["errors"] == {"date_to": ["no fiscal year"]}


def test_balances_without_cutoffs_are_empty(mb: dict[str, Any]) -> None:
    from fcp.modules.reporting.actuals import net_before_many  # noqa: PLC0415

    set_context(tenant_id=mb["ws"]["id"])
    _, balances, closings = net_before_many(mb["entity"]["id"], mb["ws"]["id"], cutoffs=[])
    assert balances == closings == {}


def close(mb: dict[str, Any], start: str) -> None:
    years = mb["client"].get(f"{mb['base']}/fiscal-years").json()
    fy = next(y for y in years if y["start_date"] == start)
    generated = mb["client"].post_json(
        f"{mb['base']}/fiscal-years/{fy['id']}/close",
        {"retained_earnings_account_id": mb["accounts"]["3200"]["id"]},
    )
    assert generated.status_code == 201, generated.content
    posted = mb["client"].post_json(
        f"{mb['base']}/journal-entries/{generated.json()['id']}/post", {}
    )
    assert posted.status_code == 200, posted.content
    commit_point()


def test_after_year_end_close_the_result_is_in_retained_earnings(two_years: dict[str, Any]) -> None:
    close(two_years, "2025-01-01")
    result = ok(two_years)
    pl, bs, cf = (result[k] for k in ("profit_and_loss", "balance_sheet", "cash_flow"))
    # The P&L of the closed year is unchanged: closing entries are not part of the result.
    assert amounts(pl, "comparative")["PL.RESULT"] == "4000.00"
    now, before = amounts(bs), amounts(bs, "comparative")
    assert now["BS.EQUITY.RETAINED"] == "4000.00"
    assert "BS.EQUITY.PRIOR_UNCLOSED" not in now  # nothing left unclosed
    assert now["BS.TOTAL.EQUITY"] == "19550.00"
    assert now["BS.TOTAL_ASSETS"] == now["BS.TOTAL_EQUITY_LIABILITIES"] == "23850.00"
    assert before["BS.EQUITY.RESULT_YTD"] == "0.00"  # closed on 2025-12-31
    assert before["BS.EQUITY.RETAINED"] == "4000.00"
    # The transfer to retained earnings is neither a cash flow nor a contribution.
    prior_cf = amounts(cf, "comparative")
    assert prior_cf["CF.RESULT"] == "4000.00"
    assert "CF.BS.EQUITY.RETAINED" not in prior_cf
    assert prior_cf["CF.NET_CHANGE"] == "14000.00"

    close(two_years, "2026-01-01")
    closed = amounts(ok(two_years)["balance_sheet"])
    assert closed["BS.EQUITY.RETAINED"] == "9550.00"
    assert closed["BS.EQUITY.RESULT_YTD"] == "0.00"
    assert amounts(ok(two_years)["profit_and_loss"])["PL.RESULT"] == "5550.00"

    verify = two_years["client"].get(f"/api/w/{two_years['ws']['slug']}/actuals/verify").json()
    assert verify["ok"] is True
    december = two_years["client"].get(
        f"{two_years['base']}/actuals/monthly", {"date_from": "2026-12-01", "date_to": "2026-12-31"}
    )
    codes = {f["account_code"] for f in december.json()["facts"]}
    assert "4000" not in codes  # planning reads operating actuals, without the closing entry


@settings(
    max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(entries=postings, start=st.dates(min_value=date(2025, 1, 1), max_value=date(2026, 12, 31)),
       days=st.integers(min_value=0, max_value=500))  # fmt: skip
def test_every_check_holds_across_a_closed_year(
    two_years: dict[str, Any], entries: list[Any], start: date, days: int
) -> None:
    years = two_years["client"].get(f"{two_years['base']}/fiscal-years").json()
    if next(y for y in years if y["start_date"] == "2025-01-01")["status"] == "OPEN":
        close(two_years, "2025-01-01")
    for day, (debit, credit), amount in entries:
        when = day if day.year == 2026 else day.replace(year=2026, day=min(day.day, 28))
        post(two_years, (debit, f"{amount:.2f}", "0"), (credit, "0", f"{amount:.2f}"),
             day=when.isoformat())  # fmt: skip
    commit_point()
    end = min(date.fromordinal(start.toordinal() + days), date(2026, 12, 31))
    ok(two_years, start.isoformat(), end.isoformat())
