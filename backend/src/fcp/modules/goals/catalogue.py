"""What a goal can track (M4-6, doc 10 §6.1).

- **Additive** metrics are sums of flows over the window (revenue, operating expenses, EBITDA,
  net profit): the required performance is a remaining amount and a run rate.
- **Ratio** metrics are KPIs from the library or approved workspace KPIs (M4-4, M4-5).
- **Balance** metrics are a balance at a date (cash): a threshold goal looks at every month end and
  every week of the 13-week cash forecast.

Formulas are in the KPI formula language, so every value explains itself down to accounts.
"""

from dataclasses import dataclass
from uuid import UUID

from fcp.core.errors import ValidationFailedError
from fcp.modules.kpi.api import trackable

ADDITIVE, RATIO, BALANCE = "ADDITIVE", "RATIO", "BALANCE"
EBITDA = (
    'flow("REVENUE") + flow("OTHER_INCOME") - flow("COST_OF_SALES") - flow("OPERATING_EXPENSES")'
)
NET_PROFIT = (
    f'{EBITDA} - flow("DEPRECIATION_AMORTISATION") + flow("INT.INCOME") - flow("INT.EXPENSE")'
    ' - flow("FX.DIFF") - flow("TAX")'
)


@dataclass(frozen=True)
class Metric:
    key: str  # "REVENUE" or "kpi:<KEY>"
    ref: str  # the definition version
    name: str
    name_el: str
    kind: str
    formula: str
    direction: str  # HIGHER_BETTER | LOWER_BETTER
    unit: str
    display: str
    convention: str = ""


BUILT_IN = (
    Metric("REVENUE", "GOALS@1.0:REVENUE", "Revenue", "Έσοδα", ADDITIVE, 'flow("REVENUE")',
           "HIGHER_BETTER", "EUR", "EUR", "The REVENUE section (sales and services)."),
    Metric("OPEX", "GOALS@1.0:OPEX", "Operating expenses", "Λειτουργικά έξοδα", ADDITIVE,
           'flow("OPERATING_EXPENSES")', "LOWER_BETTER", "EUR", "EUR",
           "The OPERATING_EXPENSES section (excluding depreciation)."),
    Metric("EBITDA", "GOALS@1.0:EBITDA", "EBITDA", "EBITDA", ADDITIVE, EBITDA, "HIGHER_BETTER",
           "EUR", "EUR", "Revenue + other income - cost of sales - operating expenses."),
    Metric("NET_PROFIT", "GOALS@1.0:NET_PROFIT", "Net profit", "Καθαρό κέρδος", ADDITIVE,
           NET_PROFIT, "HIGHER_BETTER", "EUR", "EUR",
           "EBITDA - depreciation and amortisation + interest income - interest expense"
           " - exchange differences - income tax."),
    Metric("CASH", "GOALS@1.0:CASH", "Cash", "Ταμειακά διαθέσιμα", BALANCE, 'balance("BS.CASH")',
           "HIGHER_BETTER", "EUR", "EUR",
           "Cash and equivalents (BS.CASH) at each month end, then the 13-week cash forecast."),
)  # fmt: skip

_UNITS = {"percent": "ratio", "ratio": "ratio", "times": "ratio", "days": "days",
          "months": "ratio", "EUR": "EUR"}  # fmt: skip


def metrics(entity_id: UUID) -> list[Metric]:
    """The built-in metrics, then every library and approved workspace KPI."""
    return list(BUILT_IN) + [
        Metric(
            f"kpi:{k.key}",
            k.id,
            k.name,
            k.name_el,
            RATIO,
            k.formula,
            k.direction,
            _UNITS.get(k.display, "ratio"),
            k.display,
        )
        for k in trackable(entity_id)
    ]


def metric(entity_id: UUID, key: str) -> Metric:
    for m in metrics(entity_id):
        if m.key == key:
            return m
    raise ValidationFailedError(
        f"Unknown metric {key!r}: choose a listed metric or KPI.",
        field_errors={"metric": ["unknown metric"]},
    )
