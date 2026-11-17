"""Excel and PDF exports of a report pack (M8-3, AC-MR5): every exported value equals the API's
value for the same snapshot, cell by cell (Excel) and line by line (PDF); provenance, nature and
DRAFT are shown; text is formula-safe; exports are audited and need ``reports.export``."""

import io
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from openpyxl import load_workbook

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.mgmt_reporting.exports import _amount, cell_text, pdf_lines

from ..goals.test_goals import budget, g
from ..kpi.test_kpis import k
from ..ledger.conftest import books, join
from .test_packs import act, explain_all, generate, reviewer
from .test_sections import sections

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books", "g", "k"]


def export(g: dict[str, Any], pack_id: str, fmt: str, lang: str = "en",
           client: Any = None) -> Any:  # fmt: skip
    return (client or g["client"]).get(
        f"{g['base']}/report-packs/{pack_id}/export?format={fmt}&lang={lang}"
    )


def _expected(cell: dict[str, Any]) -> Any:
    value = cell["value"]
    if value is None:
        return None
    try:
        return Decimal(value)
    except ArithmeticError:
        return value


def test_excel_equals_the_api_cell_by_cell(g: dict[str, Any]) -> None:
    budget(g)
    pack = generate(g)
    url = f"{g['base']}/report-packs/{pack['id']}"
    g["client"].post_json(f"{url}/comments", {"section": "budget", "text": '=HYPERLINK("x")'})
    g["client"].post_json(f"{url}/risks", {"title": "+Rates rise", "owner": "CFO"})
    shown = sections(g, pack["id"])
    got = export(g, pack["id"], "xlsx")
    assert got.status_code == 200, got.content
    assert got["Content-Disposition"].endswith('report-pack-2026-03-v1-draft.xlsx"')
    book = load_workbook(io.BytesIO(got.content))
    assert book.sheetnames[0] == "COVER"
    cover = [str(r[0].value) for r in book["COVER"].iter_rows() if r[0].value]
    assert cover[1] == "Management pack, March 2026"
    assert "Status: Draft · Version 1" in cover
    provenance = next(x for x in cover if x.startswith("Actuals as of"))
    assert provenance == (f"Actuals as of 2026-03-31 (ledger posting #{pack['watermark']}); "
                          "Budget Plan 2026 v1; no published projection")  # fmt: skip
    assert any(x.startswith("Natures: Actual = posted entries") for x in cover)
    assert len(book.sheetnames) == 1 + len(shown)

    checked = 0
    for index, section in enumerate(shown, start=1):
        sheet = book[f"{index:02d} {section['key']}"[:31]]
        rows = [list(r) for r in sheet.iter_rows(values_only=True)]
        assert rows[0][0] == section["title"]
        assert rows[1][0] == provenance
        at = 1
        for table in section["tables"]:
            at = next(i for i in range(at + 1, len(rows)) if rows[i][0] == table["caption"])
            assert list(rows[at + 1][: len(table["columns"])]) == [c["label"] for c in
                                                                  table["columns"]]  # fmt: skip
            assert rows[at + 2][0] == "Nature"
            for offset, row in enumerate(table["rows"], start=at + 3):
                got_row = rows[offset][1 : 1 + len(row["cells"])]
                assert [_expected(c) for c in row["cells"]] == [
                    Decimal(str(v)) if isinstance(v, (int, float, Decimal)) else v
                    for v in got_row], (section["key"], row["key"])  # fmt: skip
                checked += len(row["cells"])
    assert checked > 100
    budget_sheet = [list(r) for r in book["05 budget"].iter_rows(values_only=True)]
    natures = next(r for r in budget_sheet if r[0] == "Nature")
    assert natures[1:5] == ["Actual", "Budget", "Budget", "Actual"]
    # Formula-safe commentary and risks (threat T9).
    assert ['\'=HYPERLINK("x")'] in [[r[0]] for r in budget_sheet if r[0]]
    risk_sheet = [list(r) for r in book["08 risks"].iter_rows(values_only=True)]
    assert risk_sheet[-1][:2] == ["'+Rates rise", "OPEN"]


def test_pdf_lines_equal_the_api_and_say_draft(g: dict[str, Any], make_user: Make,
                                               api_client: Make) -> None:  # fmt: skip
    budget(g)
    pack = generate(g)
    url = f"{g['base']}/report-packs/{pack['id']}"
    g["client"].post_json(f"{url}/risks", {"title": "Rates rise", "mitigation": "Fix the rate"})
    g["client"].post_json(f"{url}/comments", {"section": "commentary", "text": "Line one\nTwo"})
    shown = sections(g, pack["id"])
    pdf = export(g, pack["id"], "pdf")
    assert (pdf.status_code, pdf["Content-Type"]) == (200, "application/pdf")
    assert pdf.content.startswith(b"%PDF")
    for section in shown:
        for table in section["tables"]:
            lines = pdf_lines(table, "en")
            assert lines[0] == [c["label"] for c in table["columns"]]
            for line, row in zip(lines[2:], table["rows"], strict=True):
                assert line[0] == row["label"]
                assert line[1:] == [
                    cell_text(c["value"], row.get("display"), "en") for c in row["cells"]
                ]
                for text, cell in zip(line[1:], row["cells"], strict=True):
                    if row.get("display") == "percent":
                        continue
                    if cell["value"] and text and text[0].isdigit() | text.startswith("-"):
                        assert Decimal(text.replace(",", "")) == Decimal(cell["value"])
    month = next(s for s in shown if s["key"] == "budget")["tables"][0]
    where = [r["key"] for r in month["rows"]].index("REV.SALES")
    sales = pdf_lines(month, "en")[2 + where]
    assert sales[1:6] == ["0.00", "1,000.00", "1,000.00", "0.00", "-1,000.00"]
    greek = pdf_lines(next(s for s in sections(g, pack["id"], "el")
                           if s["key"] == "budget")["tables"][0], "el")  # fmt: skip
    assert greek[1][0] == "Φύση"
    assert greek[2 + where][1:6] == ["0,00", "1.000,00", "1.000,00", "0,00", "-1.000,00"]
    assert export(g, pack["id"], "pdf", "el").content.startswith(b"%PDF")

    # Final: the file name drops "draft"; a read-only user cannot export; every export audited.
    boss = reviewer(g, make_user, api_client)
    explain_all(g, pack)
    act(g["client"], g, pack["id"], "regenerate")
    act(g["client"], g, pack["id"], "submit")
    assert act(boss, g, pack["id"], "finalise").status_code == 200
    final = export(g, pack["id"], "pdf")
    assert final["Content-Disposition"].endswith('report-pack-2026-03-v1.pdf"')
    viewer = join(g["client"], g["ws"]["slug"], make_user("viewer@example.test"), api_client,
                  "read_only")  # fmt: skip
    assert export(g, pack["id"], "xlsx", client=viewer).status_code == 403
    set_context(tenant_id=UUID(g["ws"]["id"]))
    events = AuditEvent.objects.filter(action="reports.exported", subject_id=pack["id"])
    assert sorted(e.changes["format"] for e in events) == ["pdf", "pdf", "pdf"]
    assert {e.changes["status"] for e in events} == {"DRAFT", "FINAL"}


def test_pdf_shows_percentages_and_goal_words() -> None:
    assert cell_text("0.2", "percent", "en") == "20.00%"
    assert cell_text("0.7712", "percent", "el") == "77,12%"
    assert cell_text("132.2775269", "days", "en") == "132.28"
    assert cell_text(None, "percent", "en") == ""
    assert _amount("On track", "en") == "On track"
