"""Projection screens' backend (M6-6): balance-sheet totals, result ids for "explain a line", and
the Excel export with a nature row (formula-safe, exact amounts)."""

import io
from decimal import Decimal
from typing import Any

import pytest
from openpyxl import load_workbook

from .test_assumptions import books, hist
from .test_projections import approved

pytestmark = pytest.mark.django_db
__all__ = ["books", "hist"]


def test_totals_explain_and_export(hist: dict[str, Any]) -> None:
    c, base = hist["client"], hist["base"]
    run = c.post_json(f"{base}/projections", {"assumption_set_id": approved(hist)}).json()
    got = c.get(f"{base}/projections/{run['id']}").json()
    rows = got["rows"]
    # Totals are sums of the rounded lines and balance in every column.
    assert rows["BS.TOTAL_ASSETS"] == rows["BS.TOTAL_LIABILITIES_EQUITY"]
    assert rows["BS.TOTAL_ASSETS"][0] == "400.00"  # cash 100 + receivables 300
    # Each cell names its stored result; the explain route shows what it came from.
    result = got["result_ids"]["PL.COGS"][1]
    explained = c.get(f"{base}/calc-runs/{run['id']}/results/{result}/explain").json()
    assert explained["result"]["series_key"] == "PL.COGS"
    assert explained["lineage"][0]["input_kind"] == "ASSUMPTION"
    assert ":gross_margin:2027-01" in explained["lineage"][0]["input_ref"]

    response = c.get(f"{base}/projections/{run['id']}/export?granularity=QUARTER&lang=el")
    assert response.status_code == 200, response.content
    assert response["Content-Disposition"].endswith('-quarter.xlsx"')
    book = load_workbook(io.BytesIO(response.content))
    assert book.sheetnames == ["IS", "BS", "CF"]
    bs = book["BS"]
    assert bs["A2"].value == "Προβλεπόμενη κατάσταση οικονομικής θέσης"
    assert str(bs["A3"].value).startswith("Πρόβλεψη (όχι πραγματικά αποτελέσματα)")
    assert [cell.value for cell in bs[6]][:3] == ["Φύση", "Πραγματικό", "Πρόβλεψη"]
    assert bs["B5"].value == "Έναρξη (πραγματικό)"
    cash = next(r for r in bs.iter_rows(min_row=7) if r[0].value == "Ταμειακά διαθέσιμα")
    assert Decimal(str(cash[1].value)) == Decimal(100)
    income = book["IS"]
    assert [cell.value for cell in income[6]][1] == "Πρόβλεψη"  # no opening column
    assert len([cell for cell in income[6] if cell.value]) == 5  # nature + 4 quarters
