"""V1-4 (#210): the numbers agree from screen to screen.

After the demo year has run through every module, each module's figures are read back through
the same API the screens use and compared with the ledger and the statements:

ledger -> statements -> budget variance -> KPIs -> cash forecast -> fixed assets -> projection ->
report pack -> VAT return.

Each check is a pair of figures that must be equal; a check that fails names both. Synthetic data
only (ADR-0010).
"""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

Call = Callable[..., Any]
PLACES = Decimal("0.000001")  # ratios are compared to six places; amounts exactly


@dataclass(frozen=True)
class Agreement:
    name: str
    left: str
    right: str

    @property
    def ok(self) -> bool:
        return self.left == self.right


def _rows(statement: dict[str, Any]) -> dict[str, str]:
    return {r["code"]: r["current"] for r in statement["rows"] if r["current"] is not None}


def _section(statement: dict[str, Any], heading: str) -> Decimal:
    """The sum of the lines under a heading of a statement, up to the next heading."""
    total, inside = Decimal(0), False
    for r in statement["rows"]:
        if r["kind"] == "heading":
            inside = r["code"] == heading
        elif inside and r["kind"] == "line":
            total += Decimal(r["current"])
    return total


def _ratio(value: Decimal | str | None) -> str:
    return "n/a" if value is None else f"{Decimal(value).quantize(PLACES, ROUND_HALF_UP)}"


def _pack_statement(pack: dict[str, Any], kind: str) -> dict[str, Any]:
    found = pack["snapshot"]["blocks"]["statements"]["data"]["statements"]
    return dict(next(s for s in found if s["kind"] == kind))


def check(  # noqa: PLR0913 - the figures each module produced in the demo
    call: Call,
    base: str,
    year: int,
    *,
    statements: dict[str, Any],
    forecast: dict[str, Any],
    budget_version: str,
    pack_id: str,
    vat_report: str,
) -> list[Agreement]:
    """Every cross-module agreement for the demo year. ``call(method, path)`` is a signed-in API
    call; ``statements`` the year's statements, read before the year-end close."""
    pl, bs = statements["profit_and_loss"], statements["balance_sheet"]
    cf = statements["cash_flow"]
    p, b, c = _rows(pl), _rows(bs), _rows(cf)
    revenue = _section(pl, "REVENUE")
    sales = next(r["current"] for r in pl["rows"] if r["code"] == "REV.SALES")
    found: list[Agreement] = []

    def agree(name: str, left: Any, right: Any) -> None:
        found.append(Agreement(name, str(left), str(right)))

    december = f"{year}-12-31"
    tb = call("GET", f"{base}/reports/trial-balance?as_of={december}")
    agree("Ledger: trial balance debits = credits", tb["total_debit"], tb["total_credit"])
    agree("Statements: cash in the balance sheet = closing cash in the cash flow",
          b["BS.CASH"], c["CF.CASH_CLOSING"])  # fmt: skip
    agree("Statements: total assets = total equity and liabilities",
          b["BS.TOTAL_ASSETS"], b["BS.TOTAL_EQUITY_LIABILITIES"])  # fmt: skip
    agree("Statements: profit for the year = profit in equity",
          p["PL.RESULT"], b["BS.EQUITY.RESULT_YTD"])  # fmt: skip

    # Budget variance: its actuals are the ledger's; its budget is the approved budget.
    variance = f"{base}/budget-versions/{budget_version}/variance?month={year + 1}-12-01&view=YTD"
    prior = call("GET", f"{variance}&comparison=ACTUAL_VS_PRIOR_YEAR")
    budget = call("GET", f"{variance}&comparison=ACTUAL_VS_BUDGET")
    version = call("GET", f"{base}/budget-versions/{budget_version}")
    agree(f"Budget variance: {year} sales (prior-year column) = sales in the statements",
          next(r["comparison"] for r in prior["rows"] if r["taxonomy_code"] == "REV.SALES"),
          sales)  # fmt: skip
    agree(f"Budget variance: {year + 1} budget column = the approved budget's sales",
          next(r["comparison"] for r in budget["rows"] if r["taxonomy_code"] == "REV.SALES"),
          next(ln["total"] for ln in version["lines"]
               if ln["taxonomy_code"] == "REV.SALES"))  # fmt: skip

    # KPIs: calculated from the same figures as the statements.
    kpis = call("POST", f"{base}/kpi-sets", {"date_from": f"{year}-01-01",
                                            "date_to": december}, 201)  # fmt: skip
    value = {v["key"]: v["value"] for v in kpis["values"]}
    agree("KPIs: gross margin = gross profit / revenue", _ratio(value["GROSS_MARGIN"]),
          _ratio(Decimal(p["PL.GROSS_PROFIT"]) / revenue))  # fmt: skip
    agree("KPIs: EBITDA margin = EBITDA / revenue", _ratio(value["EBITDA_MARGIN"]),
          _ratio(Decimal(p["PL.EBITDA"]) / revenue))  # fmt: skip
    agree("KPIs: current ratio = current assets / current liabilities",
          _ratio(value["CURRENT_RATIO"]),
          _ratio(Decimal(b["BS.TOTAL.CURRENT_ASSETS"])
                 / Decimal(b["BS.TOTAL.CURRENT_LIABILITIES"])))  # fmt: skip

    # Cash forecast: it opens at the cash the books hold.
    agree("Cash forecast: opening cash = cash in the balance sheet", forecast["opening_cash"],
          b["BS.CASH"])  # fmt: skip

    # Fixed assets: the register agrees with the ledger once depreciation is posted.
    assets = call("GET", f"{base}/fixed-assets/reconciliation?as_of={year + 1}-01-31")
    for row in assets["rows"]:
        agree(f"Fixed assets: {row['account_code']} {row['kind'].lower()} in the register = "
              "the ledger", row["register_total"], row["ledger_total"])  # fmt: skip

    # Projection: its first month starts from the closing balance sheet.
    runs = call("GET", f"{base}/projections")
    published = next(r for r in runs if r["is_published"] and not r["rolling"])
    got = call("GET", f"{base}/projections/{published['id']}?granularity=MONTH")
    month, opening_column = got["rows"], got["columns"][0]
    agree("Projection: its opening balance sheet is actual", opening_column["nature"], "ACTUAL")
    agree("Projection: opening cash = cash in the balance sheet", month["BS.CASH"][0],
          b["BS.CASH"])  # fmt: skip
    first = Decimal(month["BS.CASH"][1]) - Decimal(month["CF.NET_CHANGE"][1])
    agree("Projection: the first month starts from that opening cash", f"{first:.2f}",
          b["BS.CASH"])  # fmt: skip

    # Report pack: its frozen figures are the statements' and the KPIs are there.
    pack = call("GET", f"{base}/report-packs/{pack_id}")
    pack_bs = _rows(_pack_statement(pack, "BS"))
    agree("Report pack: total assets = the balance sheet", pack_bs["BS.TOTAL_ASSETS"],
          b["BS.TOTAL_ASSETS"])  # fmt: skip
    agree("Report pack: cash = the balance sheet", pack_bs["BS.CASH"], b["BS.CASH"])
    agree("Report pack: the KPI section is filled", pack["snapshot"]["blocks"]["kpis"]["status"],
          "ok")  # fmt: skip

    # VAT return: bridged to the VAT accounts with nothing unexplained.
    vat = call("GET", f"{base}/vat-reports/{vat_report}")
    for bridge in vat["reconciliation"]["bridges"]:
        agree(f"VAT return: boxes {bridge['boxes']} bridged to the ledger, unexplained",
              bridge["unexplained"], "0.00")  # fmt: skip
    return found
