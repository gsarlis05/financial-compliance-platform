"""Excel export of a scenario comparison (M7-7): base, scenario and difference per period under a
nature row, the change by override, formula-safe text, exact amounts, audited, and refused without
``reports.export``."""

import io
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from openpyxl import load_workbook

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.models import AuditEvent

from ..ledger.conftest import books, join
from .test_runs_api import plan, scenario

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books", "plan"]


def test_export(plan: dict[str, Any], make_user: Make, api_client: Make) -> None:
    c = plan["client"]
    surl = scenario(plan, ("PCT_CHANGE", {"driver": "revenue", "percent": "-25",
                                          "start_month": "2027-07"}))  # fmt: skip
    response = c.get(f"{surl}/comparison/export?granularity=YEAR")
    assert response.status_code == 200, response.content
    assert response["Content-Disposition"].endswith('scenario-comparison-year.xlsx"')
    book = load_workbook(io.BytesIO(response.content))
    assert book.sheetnames == ["IS", "BS", "CF", "CHANGES"]
    income = book["IS"]
    assert income["A2"].value == "Scenario income statement"
    note = str(income["A3"].value)
    assert note.startswith("Scenario ")
    assert "hypothetical: not actual results and not an approved forecast" in note
    assert "not independently certified" in note
    assert [x.value for x in income[6]][1:4] == ["Base", "Scenario", "Difference"]
    assert [x.value for x in income[7]][:4] == ["Nature"] + ["Hypothetical"] * 3
    revenue = next(r for r in income.iter_rows(min_row=8) if r[0].value == "Revenue")
    # 2027: 12,000 in the base, 1,500 less in the scenario (-25% from July).
    assert [Decimal(str(x.value)) for x in revenue[1:4]] == [
        Decimal(12000), Decimal(10500), Decimal(-1500)]  # fmt: skip
    bs = book["BS"]
    assert bs["B5"].value == "Opening (actual)"
    assert [x.value for x in bs[7]][1:4] == ["Actual"] * 3
    changes = book["CHANGES"]
    rows = [[x.value for x in r] for r in changes.iter_rows(min_row=6)]
    assert rows[-1][1] == "Total change"
    assert Decimal(str(rows[0][2])) == Decimal(str(rows[-1][2])) == Decimal(-1500)

    greek = c.get(f"{surl}/comparison/export?lang=el")
    assert load_workbook(io.BytesIO(greek.content))["IS"]["A2"].value == (
        "Κατάσταση αποτελεσμάτων σεναρίου"
    )
    set_context(tenant_id=UUID(plan["ws"]["id"]))
    audits = AuditEvent.objects.filter(action="reports.exported", subject_id="scenario_comparison")
    assert audits.count() == 2

    viewer = join(c, plan["ws"]["slug"], make_user("viewer@example.test"), api_client,
                  "read_only")  # fmt: skip
    assert viewer.get(f"{surl}/comparison/export").status_code == 403
