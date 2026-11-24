"""Budget phasing on save, department owners and the hardened Excel import/export (M4-2:
AC-BU2, AC-BU3, AC-BU6)."""

import io
import zipfile
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook, load_workbook

from ..ledger.conftest import books, join
from ..metrics.test_mapping import defaults, post
from .test_budgets import MONTHS

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books"]


@pytest.fixture
def g(books: dict[str, Any], make_user: Make, api_client: Make) -> dict[str, Any]:
    base, slug = books["base"], books["ws"]["slug"]
    books["client"].put_json(f"{base}/ledger-settings", {"approval_policy": "NONE"})
    dim = books["client"].post_json(
        f"{base}/dimensions", {"code": "DEPT", "name": "Department", "kind": "DEPARTMENT"}
    )
    values = {}
    for code in ("SALES", "OPS"):
        made = books["client"].post_json(
            f"{base}/dimensions/{dim.json()['id']}/values", {"code": code, "name": code.title()}
        )
        values[code] = made.json()["id"]
    books["dims"] = values
    books["holder_user"] = make_user("holder@example.test", "Hana Holder")
    books["holder"] = join(books["client"], slug, books["holder_user"], api_client, "budget_holder")
    budget = books["client"].post_json(
        f"{base}/budgets", {"name": "B26", "fiscal_year_id": books["fy"]["id"]}
    )
    books["budget"] = budget.json()
    books["v1"] = budget.json()["open_version_id"]
    return books


def lines_url(g: dict[str, Any]) -> str:
    return f"{g['base']}/budget-versions/{g['v1']}/lines"


def put(g: dict[str, Any], lines: list[dict[str, Any]], client: Any = None) -> Any:
    return (client or g["client"]).put_json(lines_url(g), {"lines": lines})


def test_phasing_methods_on_save_and_preview(g: dict[str, Any]) -> None:
    # Last year's sales: twice as much in March as in January, nothing else.
    g["client"].post_json(f"{g['base']}/fiscal-years", {"start_date": "2025-01-01"})
    defaults(g)
    post(g, ("1300", "1000.00", "0"), ("4000", "0", "1000.00"), day="2025-01-10")
    post(g, ("1300", "2000.00", "0"), ("4000", "0", "2000.00"), day="2025-03-10")
    post(g, ("1300", "5.00", "0"), ("4000", "0", "5.00"), day="2025-12-31")
    saved = put(
        g,
        [
            {"taxonomy_code": "REV.SALES", "method": "SEASONAL", "params": {"annual": "3005.00"}},
            {"taxonomy_code": "OPEX.RENT", "method": "EVEN", "params": {"annual": "100000.00"}},
            {
                "taxonomy_code": "OPEX.PAYROLL",
                "method": "DRIVER",
                "params": {"quantity": "3", "rate": "2500.555"},
            },
            {
                "taxonomy_code": "OPEX.OTHER",
                "method": "PROFILE",
                "params": {"annual": "1200", "weights": ["1"] * 6 + ["3"] * 6},
            },
            {"taxonomy_code": "OPEX.TRAVEL", "method": "SEASONAL", "params": {"annual": "12.00"}},
        ],
    )
    assert saved.status_code == 200, saved.content
    sales, rent, payroll, other, travel = saved.json()["lines"]
    assert sales["amounts"][0] == "1000.00"
    assert sales["amounts"][2] == "2000.00"
    assert sales["amounts"][11] == "5.00"
    assert sales["total"] == "3005.00"
    assert sales["phasing_note"] == "Phased like the prior year's actuals."
    assert rent["amounts"][:11] == ["8333.33"] * 11
    assert rent["amounts"][11] == "8333.37"
    assert rent["total"] == "100000.00"
    assert payroll["amounts"] == ["7501.67"] * 12
    assert other["amounts"][0] == "50.00"
    assert other["amounts"][6] == "150.00"
    assert other["total"] == "1200.00"
    assert travel["phasing_note"] == "No prior-year actuals for this line; phased evenly."
    assert sales["method"] == "SEASONAL"
    assert sales["method_params"]["annual"] == "3005.00"

    preview = g["client"].post_json(
        f"{g['base']}/budget-versions/{g['v1']}/phase",
        {"taxonomy_code": "REV.SALES", "method": "EVEN", "params": {"annual": "0.10"}},
    )
    assert preview.status_code == 200, preview.content
    assert preview.json()["amounts"] == ["0.00"] * 11 + ["0.10"]
    bad = put(
        g,
        [
            {
                "taxonomy_code": "OPEX.RENT",
                "method": "PROFILE",
                "params": {"annual": "1", "weights": ["1"]},
            }
        ],
    )
    assert bad.status_code == 422
    assert "12 values" in str(bad.json())
    manual = g["client"].post_json(
        f"{g['base']}/budget-versions/{g['v1']}/phase",
        {"taxonomy_code": "REV.SALES", "method": "MANUAL", "params": {}},
    )
    assert manual.status_code == 422


def test_department_owner_sees_and_edits_only_their_department(g: dict[str, Any]) -> None:
    sales, ops = g["dims"]["SALES"], g["dims"]["OPS"]
    holder = g["holder"]
    assert (
        put(
            g,
            [
                {
                    "taxonomy_code": "OPEX.RENT",
                    "dimension_value_id": ops,
                    "amounts": {MONTHS[0]: "10.00"},
                },
                {
                    "taxonomy_code": "OPEX.TRAVEL",
                    "dimension_value_id": sales,
                    "amounts": {MONTHS[0]: "5.00"},
                },
            ],
        ).status_code
        == 200
    )
    # Not yet named: the budget does not exist for the holder.
    assert holder.get(f"{g['base']}/budgets").json() == []
    assert holder.get(lines_url(g).removesuffix("/lines")).status_code == 404
    owners = f"{g['base']}/budgets/{g['budget']['id']}/owners"
    members = g["client"].get(f"{g['base']}/budget-members").json()
    holder_id = str(g["holder_user"].id)
    assert holder_id in {m["user_id"] for m in members}
    assert holder.put_json(owners, {"owners": []}).status_code == 403
    assert (
        g["client"]
        .put_json(owners, {"owners": [{"dimension_value_id": sales, "user_id": str(uuid4())}]})
        .status_code
        == 422
    )
    assert (
        g["client"]
        .put_json(owners, {"owners": [{"dimension_value_id": str(uuid4()), "user_id": holder_id}]})
        .status_code
        == 422
    )
    named = g["client"].put_json(
        owners, {"owners": [{"dimension_value_id": sales, "user_id": holder_id}]}
    )
    assert named.status_code == 200, named.content
    assert named.json()[0]["user_name"] == "Hana Holder"

    seen = holder.get(lines_url(g).removesuffix("/lines")).json()
    assert [ln["taxonomy_code"] for ln in seen["lines"]] == ["OPEX.TRAVEL"]
    assert seen["total"] == "5.00"
    assert [b["id"] for b in holder.get(f"{g['base']}/budgets").json()] == [g["budget"]["id"]]
    # The holder replaces only their department's lines; Ops stays untouched.
    edited = put(
        g,
        [
            {
                "taxonomy_code": "OPEX.TRAVEL",
                "dimension_value_id": sales,
                "amounts": {MONTHS[0]: "7.00"},
            },
            {
                "taxonomy_code": "OPEX.MARKETING",
                "dimension_value_id": sales,
                "amounts": {MONTHS[1]: "3.00"},
            },
        ],
        holder,
    )
    assert edited.status_code == 200, edited.content
    assert edited.json()["total"] == "10.00"
    full = g["client"].get(lines_url(g).removesuffix("/lines")).json()
    assert [(ln["taxonomy_code"], ln["total"]) for ln in full["lines"]] == [
        ("OPEX.RENT", "10.00"),
        ("OPEX.TRAVEL", "7.00"),
        ("OPEX.MARKETING", "3.00"),
    ]
    assert (
        put(g, [{"taxonomy_code": "OPEX.RENT", "dimension_value_id": ops}], holder).status_code
        == 422
    )
    assert put(g, [{"taxonomy_code": "OPEX.RENT"}], holder).status_code == 422
    # Everything else stays with preparers and approvers.
    version = f"{g['base']}/budget-versions/{g['v1']}"
    assert holder.post_json(f"{version}/submit", {}).status_code == 403
    assert (
        holder.post_json(
            f"{g['base']}/budgets", {"name": "x", "fiscal_year_id": g["fy"]["id"]}
        ).status_code
        == 403
    )
    assert holder.get(owners).status_code == 403
    exported = holder.get(f"{version}/export")
    assert exported.status_code == 200
    sheet = load_workbook(io.BytesIO(exported.content)).active
    assert sheet is not None
    assert [r[0] for r in sheet.iter_rows(min_row=5, values_only=True)] == [
        "OPEX.TRAVEL",
        "OPEX.MARKETING",
    ]
    g["client"].get(f"{g['base']}/budgets")  # end under the owner's context


def workbook(rows: list[list[Any]], header: list[Any] | None = None) -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(["Budget"])
    sheet.append([])
    sheet.append(
        header or ["Line", "Account", "Dimension", "Note", *(m[:7] for m in MONTHS), "Total"]
    )
    for row in rows:
        sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def upload(g: dict[str, Any], data: bytes, query: str = "", client: Any = None) -> Any:
    return (client or g["client"]).post(
        f"{g['base']}/budget-versions/{g['v1']}/import{query}",
        {"file": SimpleUploadedFile("b.xlsx", data)},
        headers=(client or g["client"])._csrf(),
    )


def test_export_then_import_round_trip_with_preview_and_hash(g: dict[str, Any]) -> None:
    put(
        g,
        [
            {"taxonomy_code": "REV.SALES", "amounts": dict.fromkeys(MONTHS, "100.00")},
            {
                "account_id": g["accounts"]["6100"]["id"],
                "dimension_value_id": g["dims"]["OPS"],
                "amounts": {MONTHS[0]: "-1.50"},
                "note": "=cmd|' /C calc'!A0",
            },
        ],
    )
    exported = g["client"].get(f"{g['base']}/budget-versions/{g['v1']}/export")
    assert exported["Content-Type"].startswith("application/vnd.openxmlformats")
    sheet = load_workbook(io.BytesIO(exported.content)).active
    assert sheet is not None
    assert "nature BUDGET" in str(sheet["A2"].value)
    rows = list(sheet.iter_rows(min_row=4, values_only=True))
    assert rows[0][:5] == ("Line", "Account", "Dimension", "Note", "2026-01")
    assert rows[2][:4] == (None, "6100", "DEPT:OPS", "'=cmd|' /C calc'!A0")  # neutralised
    assert rows[1][-1] == 1200  # the total is a number, never a formula

    # Importing the export unchanged changes nothing (the note now starts with ').
    same = upload(g, exported.content)
    assert same.status_code == 200, same.content
    body = same.json()
    assert body["problems"] == []
    assert body["unchanged"] == 2
    assert body["changes"] == []

    edited = workbook(
        [
            ["REV.SALES", None, None, "", *(["150.00"] * 12)],
            ["OPEX.RENT", None, "DEPT:SALES", "new", 10, *([0] * 11)],
        ]
    )
    preview = upload(g, edited).json()
    assert preview["applied"] is False
    assert sorted((c["kind"], c["line"].split(" ")[0]) for c in preview["changes"]) == [
        ("ADDED", "OPEX.RENT"),
        ("CHANGED", "REV.SALES"),
        ("REMOVED", g["accounts"]["6100"]["id"]),
    ]
    changed = next(c for c in preview["changes"] if c["kind"] == "CHANGED")
    assert (changed["before"], changed["after"], changed["months_changed"]) == (
        "1200.00",
        "1800.00",
        12,
    )
    assert upload(g, edited, "?apply=true&expected_hash=stale").status_code == 409
    applied = upload(g, edited, f"?apply=true&expected_hash={preview['draft_hash']}")
    assert applied.status_code == 200, applied.content
    assert applied.json()["applied"] is True
    after = g["client"].get(f"{g['base']}/budget-versions/{g['v1']}").json()
    assert after["total"] == "1810.00"


@pytest.mark.parametrize(
    ("rows", "column", "message"),
    [
        ([["REV.SALES", None, None, "", "=1+1"]], "E", "Formulas are not accepted"),
        ([["REV.SALES", None, None, "@SUM(A1)"]], "D", "cannot start"),
        ([['=HYPERLINK("x")', None, None, ""]], "A", "Formulas are not accepted"),
        ([["+REV.SALES", None, None, ""]], "A", "cannot start"),
        ([["REV.SALES", None, None, "", "abc"]], "E", "Enter a number"),
        ([["REV.SALES", None, None, "", "1.234"]], "E", "at most 2 decimals"),
        ([["REV.SALES", None, None, "", 1.005]], "E", "at most 2 decimals"),
        ([["REV.SALES", None, None, "", True]], "E", "TRUE or FALSE"),
        ([["REV.SALES", None, None, "", "-5"]], "E", "negative amounts as numbers"),
        ([["NOPE", None, None, ""]], "A", "Unknown taxonomy line"),
        ([[None, "0000X", None, ""]], "B", "non-postable account"),
        ([["REV.SALES", "4000", None, ""]], "A", "either Line"),
        ([["REV.SALES", None, "DEPT:NONE", ""]], "C", "Unknown dimension value"),
        ([["REV.SALES"], ["REV.SALES"]], "A", "Same line as row 4"),
        ([["REV.SALES", None, None, "x" * 301]], "D", "too long"),
    ],
)
def test_import_rejects_bad_cells_with_row_and_column(
    g: dict[str, Any], rows: list[list[Any]], column: str, message: str
) -> None:
    result = upload(g, workbook(rows))
    assert result.status_code == 200, result.content
    problems = result.json()["problems"]
    assert any(p["column"] == column and message in p["message"] for p in problems), problems
    assert (
        upload(
            g, workbook(rows), f"?apply=true&expected_hash={result.json()['draft_hash']}"
        ).json()["applied"]
        is False
    )


def test_import_rejects_formulas_headers_and_unreadable_files(g: dict[str, Any]) -> None:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(["Line", "Account", "Dimension", "Note", "2026-01", "2027-01", "Colour"])
    sheet.append(["REV.SALES", None, None, None, "=1+1"])
    out = io.BytesIO()
    book.save(out)
    problems = upload(g, out.getvalue()).json()["problems"]
    messages = {(p["row"], p["column"]): p["message"] for p in problems}
    assert "Formulas are not accepted" in messages[(2, "E")]
    assert "not a month of this fiscal year" in messages[(1, "F")]
    assert "Unknown column" in messages[(1, "G")]
    missing = upload(g, workbook([], header=["Line", "Note"])).json()["problems"]
    assert any("'Account' is missing" in p["message"] for p in missing)

    def refused(data: bytes, text: str) -> None:
        response = upload(g, data)
        assert response.status_code == 422, response.content
        assert text in str(response.json())

    refused(b"", "empty")
    refused(b"col1,col2\n1,2\n", "not an .xlsx")
    refused(b"PK\x03\x04broken", "not an .xlsx")
    refused(b"PK" + b"\x03\x04" + b"0" * (5 * 1024 * 1024), "larger than 5 MB")
    refused(workbook([], header=["Nothing"]), "No header row")
    for extra, text in (("xl/vbaProject.bin", "macros"), (None, "not an .xlsx")):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            if extra:
                archive.writestr("xl/workbook.xml", "<workbook/>")
                archive.writestr(extra, b"\0")
        refused(data.getvalue(), text)
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("xl/big.xml", b"\0" * (51 * 1024 * 1024))
    refused(bomb.getvalue(), "too large once unpacked")
    fake = io.BytesIO()
    with zipfile.ZipFile(fake, "w") as archive:
        archive.writestr("xl/workbook.xml", "<not-a-workbook")
    refused(fake.getvalue(), "could not be read")


def test_owner_edge_cases_and_unusual_cells(g: dict[str, Any]) -> None:
    from datetime import datetime  # noqa: PLC0415

    sales, ops = g["dims"]["SALES"], g["dims"]["OPS"]
    holder_id = str(g["holder_user"].id)
    made = (
        g["client"]
        .post_json(
            f"{g['base']}/budgets",
            {
                "name": "Sales dept",
                "fiscal_year_id": g["fy"]["id"],
                "kind": "DEPARTMENTAL",
                "dimension_value_id": sales,
            },
        )
        .json()
    )
    owners = f"{g['base']}/budgets/{made['id']}/owners"
    assert (
        g["client"]
        .put_json(owners, {"owners": [{"dimension_value_id": ops, "user_id": holder_id}]})
        .status_code
        == 422
    )
    assert (
        g["client"].put_json(f"{g['base']}/budgets/{uuid4()}/owners", {"owners": []}).status_code
        == 404
    )
    assert (
        g["client"]
        .put_json(owners, {"owners": [{"dimension_value_id": sales, "user_id": holder_id}]})
        .status_code
        == 200
    )
    assert g["client"].get(owners).json()[0]["dimension_value_id"] == sales
    holder = g["holder"]
    url = f"{g['base']}/budget-versions/{made['open_version_id']}"
    # A departmental budget's lines take its department, also for its owner.
    saved = holder.put_json(
        f"{url}/lines",
        {"lines": [{"taxonomy_code": "OPEX.TRAVEL", "amounts": {MONTHS[0]: "1.00"}}]},
    )
    assert saved.status_code == 200, saved.content
    assert saved.json()["lines"][0]["dimension_value_id"] == sales
    seasonal = holder.put_json(
        f"{url}/lines",
        {
            "lines": [
                {"taxonomy_code": "OPEX.TRAVEL", "method": "SEASONAL", "params": {"annual": "1"}}
            ]
        },
    )
    assert seasonal.status_code == 422
    assert "permission to see reports" in str(seasonal.json())
    other = workbook([["OPEX.RENT", None, "DEPT:OPS", ""]])
    response = holder.post(
        f"{url}/import", {"file": SimpleUploadedFile("b.xlsx", other)}, headers=holder._csrf()
    )
    assert "your own departments" in str(response.json()["problems"])

    # Header months as real dates, extra cells beyond the header, dates and huge numbers.
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(["Line", "Account", "Dimension", "Note", datetime(2026, 1, 1), "2026-13"])  # noqa: DTZ001 (Excel dates have no time zone)
    sheet.append(["REV.SALES", None, None, None, datetime(2026, 5, 1), None, "extra"])  # noqa: DTZ001
    sheet.append(["REV.OTHER", None, None, None, 10**30])
    out = io.BytesIO()
    book.save(out)
    problems = upload(g, out.getvalue()).json()["problems"]
    found = {(p["row"], p["column"]): p["message"] for p in problems}
    assert found[(2, "E")] == "Enter a number."
    assert "fewer than 16 digits" in found[(3, "E")]
    assert "Unknown column '2026-13'" in found[(1, "F")]
    late = Workbook()
    sheet = late.active
    assert sheet is not None
    for _ in range(12):
        sheet.append(["junk"])
    sheet.append(["Line", "Account"])
    data = io.BytesIO()
    late.save(data)
    assert "No header row" in str(upload(g, data.getvalue()).json())
    g["client"].get(f"{g['base']}/budgets")  # end under the owner's context


def test_row_limit(g: dict[str, Any]) -> None:
    from fcp.modules.budgeting import excel  # noqa: PLC0415

    rows = [["REV.SALES"] for _ in range(excel.MAX_ROWS + 1)]
    problems = upload(g, workbook(rows)).json()["problems"]
    assert any("At most 5000 rows" in p["message"] for p in problems)
