"""Working-capital forecasting (M7-4, AC-WC1): balances and days equal the projection's, and the
value of N days equals the difference of two engine runs. Figures worked out by hand on the
synthetic base of ``test_runs`` (sales 10,000 a month at 40%: cost of sales 6,000; DSO 30, DPO 20,
no stock days)."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest

from fcp.core.errors import ValidationFailedError
from fcp.modules.projections.api import project
from fcp.modules.scenarios import working_capital as wc

from ..ledger.conftest import books, join
from .test_runs import base
from .test_runs_api import plan

Make = Callable[..., Any]
D = Decimal
__all__ = ["books", "plan"]


def test_table_by_hand() -> None:
    """January (31 days): receivables 10,000 x 30 / 31 = 9,677.42; payables 6,000 x 20 / 31 =
    3,870.97; net 5,806.45, all new (the cut-over had none), so cash falls by 5,806.45. February
    (28 days): 10,714.29 and 4,285.71, net 6,428.58, a further 622.13. CCC = 30 + 0 - 20 = 10."""
    inp = base()
    p, _ = project(inp)
    rows = wc.table(p, inp)
    jan, feb = rows[0], rows[1]
    assert (jan.receivables, jan.payables, jan.inventory) == (D("9677.42"), D("3870.97"), D("0.00"))
    assert (jan.net, jan.change, jan.cash_effect) == (D("5806.45"), D("5806.45"), D("-5806.45"))
    assert (feb.receivables, feb.payables, feb.net) == (D("10714.29"), D("4285.71"), D("6428.58"))
    assert (feb.change, feb.cash_effect) == (D("622.13"), D("-622.13"))
    assert (jan.dso, jan.dio, jan.dpo, jan.ccc) == (D(30), D(0), D(20), D(10))
    # AC-WC1: the view's balances are the projection's balance sheet.
    for row, m in zip(rows, p.months, strict=True):
        assert (row.receivables, row.inventory, row.payables) == (
            m.bs["BS.AR"],
            m.bs["BS.INVENTORY"],
            m.bs["BS.AP"],
        )


def test_value_of_days_by_hand() -> None:
    """Customers paying 10 days sooner: December receivables 10,000 x 20 / 31 = 6,451.61 instead
    of 9,677.42, so 3,225.81 more cash at the end (nothing else changes: no tax, no interest on
    cash)."""
    d = wc.value_of_days(base(), "dso", -10)
    assert d.closing_cash_change == D("3225.81")
    assert d.net_working_capital_change == D("-3225.81")
    assert d.by_month[0][1] == D("3225.81")  # 10,000 x 10 / 31 in January already
    assert d.lowest_cash_change > 0
    # AC-WC1: the value is the difference of two engine runs.
    later = wc.value_of_days(base(), "dpo", 15)
    # Each balance is rounded to cents on its own (doc 10 §2.4): payables 6,000 x 35 / 31 =
    # 6,774.19 against 6,000 x 20 / 31 = 3,870.97, a difference of 2,903.22.
    assert later.closing_cash_change == D("2903.22")
    for bad, field in ((("dso", 0), "days"), (("revenue", 5), "driver"), (("dio", 400), "days")):
        with pytest.raises(ValidationFailedError) as refused:
            wc.value_of_days(base(), *bad)
        assert list(refused.value.field_errors) == [field]


@pytest.mark.django_db
def test_api(plan: dict[str, Any], make_user: Make, api_client: Make) -> None:
    """The plan: sales 1,000 a month and no days set (an empty start), so no working capital;
    customers taking 30 days ties up 1,000 x 30 / 31 = 967.74 by December."""
    c, url = plan["client"], f"{plan['base']}/working-capital"
    got = c.get(f"{url}?base_set_id={plan['set_id']}")
    assert got.status_code == 200, got.content
    v = got.json()
    assert (v["nature"], v["cutover"], len(v["months"])) == ("FORECAST", "2026-12-31", 12)
    assert v["observed"] == {"dso": "0", "dio": "0", "dpo": "0"}
    assert v["months"][0]["net"] == "0.00"
    worth = c.post_json(f"{url}/days-worth", {"base_set_id": plan["set_id"], "driver": "dso",
                                              "days": 30}).json()  # fmt: skip
    assert (worth["closing_cash_change"], worth["net_working_capital_change"]) == (
        "-967.74",
        "967.74",
    )
    assert worth["nature"] == "HYPOTHETICAL"
    assert c.get(url).status_code == 422  # no base named
    viewer = join(c, plan["ws"]["slug"], make_user("viewer@example.test"), api_client,
                  "read_only")  # fmt: skip
    assert viewer.get(f"{url}?base_set_id={plan['set_id']}").status_code == 403
