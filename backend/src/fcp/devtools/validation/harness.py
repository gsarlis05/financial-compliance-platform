"""The projection engine's validation package (M6F-8, #153; owner decision D9).

Runs every scenario of ``docs/validation/scenarios`` through the engine and through the
independent model (``docs/validation/model/independent_model.py``, which imports nothing from the
platform), compares every statement line of every month at the EUR 0.01 tolerance, and writes the
results to ``docs/validation/results``::

    python -m fcp.devtools.validation            # writes the results
    python -m fcp.devtools.validation --check    # fails if they are out of date or do not pass

It never marks the engine as validated: that needs the professional review (method §7).
"""

import argparse
import csv
import importlib.util
import io
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

from fcp.core import reviews
from fcp.modules.projections.debt import LoanTerms, opening_current
from fcp.modules.projections.engine import EngineInput, Month, project
from fcp.modules.projections.tax import TaxInputs, TaxYearRule

ROOT = Path(__file__).resolve().parents[5] / "docs" / "validation"
TOLERANCE = Decimal("0.01")
D = Decimal
AREAS = {
    "Depreciation": ("PL.DA", "BS.PPE.ACCDEP", "CF.DA"),
    "Tax": ("PL.TAX.CURRENT", "PL.TAX.DEFERRED", "PL.TAX", "BS.INCOME_TAX", "BS.DEFERRED_TAX",
            "CF.TAX_EXPENSE", "CF.TAX_PAID"),
    "Financing": ("PL.INTEREST", "BS.DEBT.NONCURRENT", "BS.DEBT.CURRENT", "CF.BORROWING",
                  "CF.REPAYMENT", "CF.REVOLVER", "CF.SHARE_CAPITAL", "CF.DIVIDENDS",
                  "CF.FINANCING", "BS.EQUITY.SHARE_CAPITAL"),
    "Working capital": ("BS.AR", "BS.INVENTORY", "BS.AP", "CF.WC.AR", "CF.WC.INVENTORY",
                        "CF.WC.AP"),
    "Capital expenditure": ("BS.PPE.GROSS", "CF.CAPEX", "CF.INVESTING"),
    "Cash": ("BS.CASH", "CF.OPENING_CASH", "CF.CLOSING_CASH", "CF.NET_CHANGE", "CF.OPERATING"),
    "Income statement": ("PL.REVENUE", "PL.COGS", "PL.GROSS_PROFIT", "PL.OPEX", "PL.EBITDA",
                         "PL.EBIT", "PL.PBT", "PL.NET_INCOME"),
    "Equity": ("BS.EQUITY.RETAINED",),
}  # fmt: skip


def independent() -> ModuleType:
    """The independent model, loaded from its file (it is not part of the platform)."""
    path = ROOT / "model" / "independent_model.py"
    spec = importlib.util.spec_from_file_location("independent_model", path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["independent_model"] = module
    spec.loader.exec_module(module)
    return module


def _month(text: str) -> date:
    return date.fromisoformat(text + "-01" if len(text) == 7 else text)


def _series(value: Any, months: list[date]) -> dict[date, Decimal]:
    if isinstance(value, str | int):
        return dict.fromkeys(months, D(str(value)))
    return {_month(k): D(str(v)) for k, v in value.items()}


def _loan(raw: dict[str, Any], months: list[date]) -> LoanTerms:
    return LoanTerms(
        code=raw["code"], structure=raw["structure"], term_months=raw["term_months"],
        annual_rate=D(str(raw["annual_rate"])), opening=D(raw.get("opening", "0")),
        amount=D(raw.get("amount", "0")),
        drawdown_month=_month(raw["drawdown_month"]) if raw.get("drawdown_month") else None,
        interest_only_months=raw.get("interest_only_months", 0),
        rate_path=_series(raw.get("rate_path", {}), months),
        prepayments=_series(raw.get("prepayments", {}), months),
        drawdowns=_series(raw.get("drawdowns", {}), months),
    )  # fmt: skip


def _tax(raw: dict[str, Any]) -> TaxInputs:
    rules = {}
    for r in raw["rules"]:
        y = int(r["year"])
        instalments = tuple((date(y, *map(int, day.split("-"))), D(share))
                            for day, share in r["instalments"])  # fmt: skip
        final = date(y + 1, *map(int, r["final"].split("-")))
        rules[y] = TaxYearRule(y, D(r["rate"]), int(r["carry"]), instalments, final,
                               f"VALIDATION:{y}", False)  # fmt: skip
    return TaxInputs(
        rules=rules, losses_bf={int(y): D(a) for y, a in raw.get("losses_bf", {}).items()},
        allowances={int(y): D(a) for y, a in raw.get("allowances", {}).items()},
        qualifying_dep={_month(m): D(a) for m, a in raw.get("qualifying_dep", {}).items()},
        recognise_loss_dta=bool(raw.get("recognise_loss_dta", False)),
    )  # fmt: skip


def engine_input(raw: dict[str, Any]) -> EngineInput:
    """The scenario as the engine's input (the engine's own types)."""
    first = _month(raw["first_month"])
    months = [date(first.year + (first.month - 1 + n) // 12, (first.month - 1 + n) % 12 + 1, 1)
              for n in range(raw["months"])]  # fmt: skip
    drivers = {tuple(key.split(":", 1)): _series(v, months) for key, v in raw["drivers"].items()}
    reg = raw.get("register_depreciation", {})
    register = ({m: D(reg["amount"]) for m in months[: reg["months"]]} if "amount" in reg
                else _series(reg, months))  # fmt: skip
    loans = tuple(_loan(r, months) for r in raw.get("loans", []))
    opening = {k: D(v) for k, v in raw["opening"].items()}
    if raw.get("split_opening_debt"):
        current = sum((opening_current(loan, months[0]) for loan in loans
                       if loan.drawdown_month is None), D(0))  # fmt: skip
        total = opening.get("BS.DEBT.CURRENT", D(0)) + opening.get("BS.DEBT.NONCURRENT", D(0))
        opening["BS.DEBT.CURRENT"], opening["BS.DEBT.NONCURRENT"] = current, total - current
    return EngineInput(
        raw["name"], date.fromisoformat(raw["cutover"]), months, opening,
        drivers,
        register, {m for m in months if m.month == 1}, loans=loans,
        tax=_tax(raw["tax"]) if raw.get("tax") else None,
    )  # fmt: skip


@dataclass
class Difference:
    key: str
    month: str
    engine: Decimal
    model: Decimal

    @property
    def amount(self) -> Decimal:
        return abs(self.engine - self.model)


@dataclass
class Result:
    name: str
    slug: str
    description: str
    months: int
    compared: int = 0
    exact: int = 0
    max_difference: Decimal = Decimal(0)
    discrepancies: list[Difference] = field(default_factory=list)
    reconciliation: list[tuple[str, str, bool]] = field(default_factory=list)
    invariants: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    areas: dict[str, tuple[int, Decimal]] = field(default_factory=dict)  # values, max difference
    loans_compared: int = 0
    loan_discrepancies: list[str] = field(default_factory=list)
    payments_engine: list[str] = field(default_factory=list)
    payments_model: list[str] = field(default_factory=list)
    model: list[Any] = field(default_factory=list, repr=False)
    engine: list[Month] = field(default_factory=list, repr=False)

    @property
    def passed(self) -> bool:
        return (not self.discrepancies and not self.loan_discrepancies
                and all(ok for _, _, ok in self.reconciliation) and all(self.invariants.values())
                and self.payments_engine == self.payments_model)  # fmt: skip


def run_scenario(path: Path, im: ModuleType) -> Result:
    raw = json.loads(path.read_text())
    scenario = im.load(path)
    model = im.run(scenario)
    projection = project(engine_input(raw))
    r = Result(raw["name"], path.stem, raw["description"], raw["months"], model=model,
               engine=projection.months)  # fmt: skip
    r.invariants = {k: v for k, v in projection.invariants.items() if "@" not in k}
    r.invariants |= {k: v for k, v in projection.invariants.items() if "@" in k and not v}
    r.notes = list(projection.notes)
    r.reconciliation = im.reconcile(scenario, model)
    area_of = {key: area for area, keys in AREAS.items() for key in keys}
    for e, m in zip(projection.months, model, strict=True):
        tag = m.month.isoformat()[:7]
        for statement in ("pl", "bs", "cf"):
            for key, value in getattr(m, statement).items():
                found = getattr(e, statement)[key]
                diff = Difference(key, tag, found, value)
                r.compared += 1
                r.exact += found == value
                r.max_difference = max(r.max_difference, diff.amount)
                if diff.amount > TOLERANCE:
                    r.discrepancies.append(diff)
                area = area_of.get(key)
                if area:
                    count, worst = r.areas.get(area, (0, D(0)))
                    r.areas[area] = (count + 1, max(worst, diff.amount))
        for code, row in m.loans.items():
            mine = e.loans[code]
            pairs = {"interest": (mine.interest, row.interest),
                     "principal": (mine.principal, row.principal),
                     "prepayment": (mine.prepayment, row.prepayment),
                     "drawdown": (mine.drawdown, row.drawdown),
                     "closing": (mine.closing, row.closing),
                     "current": (mine.current, row.current)}  # fmt: skip
            for name, (a, b) in pairs.items():
                r.loans_compared += 1
                if abs(a - b) > TOLERANCE:
                    r.loan_discrepancies.append(f"{tag} {code} {name}: engine {a}, model {b}")
        if e.tax is not None:
            r.payments_engine += [f"{tag} {p.kind} {p.amount}" for p in e.tax.payments]
        r.payments_model += [f"{tag} {kind} {amount}" for kind, amount in m.tax.get("payments", [])]
    return r


def run_all() -> list[Result]:
    im = independent()
    return [run_scenario(p, im) for p in sorted((ROOT / "scenarios").glob("*.json"))]


# --- outputs -------------------------------------------------------------------------------------


def _table(months: list[Any], rows: list[tuple[str, list[Decimal]]]) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["line", *(m.isoformat()[:7] for m in months)])
    for key, values in rows:
        w.writerow([key, *(f"{v:.2f}" for v in values)])
    return out.getvalue()


def statements_csv(months: list[Any]) -> str:
    keys = [*months[0].pl, *months[0].bs, *months[0].cf]
    rows = [(k, [{**m.pl, **m.bs, **m.cf}[k] for m in months]) for k in keys]
    return _table([m.month for m in months], rows)


def comparison_csv(r: Result) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["month", "line", "engine", "independent model", "difference", "within EUR 0.01"])
    for e, m in zip(r.engine, r.model, strict=True):
        for statement in ("pl", "bs", "cf"):
            for key, value in getattr(m, statement).items():
                found = getattr(e, statement)[key]
                w.writerow([m.month.isoformat()[:7], key, f"{found:.2f}", f"{value:.2f}",
                            f"{found - value:.2f}", "yes" if abs(found - value) <= TOLERANCE
                            else "NO"])  # fmt: skip
    return out.getvalue()


def reconciliation_csv(r: Result) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["month", "check", "holds"])
    for tag, name, ok in r.reconciliation:
        w.writerow([tag, name, "yes" if ok else "NO"])
    return out.getvalue()


def summary_md(results: list[Result]) -> str:
    lines = [
        "# Validation results (generated)",
        "",
        "Generated by `python -m fcp.devtools.validation` from `docs/validation/scenarios`; do not "
        "edit by hand. The method, rounding rules and tolerance are in `01-scope-and-method.md`.",
        "",
        f"Engine validation status: **{reviews.engine_status()}**. {reviews.engine_note()} "
        "Passing these comparisons does not certify the engine: only a qualified independent "
        "professional's review of the package and signature of `05-reviewer-sign-off.md` does "
        "(method §7).",
        "",
        "| Scenario | Months | Values compared | Exactly equal | Largest difference "
        "| Over EUR 0.01 | Model reconciliation checks | Engine invariants | Result |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        failed = sum(1 for *_, ok in r.reconciliation if not ok)
        broken = [k for k, v in r.invariants.items() if not v]
        lines.append(
            f"| {r.name} | {r.months} | {r.compared} | {r.exact} | {r.max_difference:.2f} | "
            f"{len(r.discrepancies)} | {len(r.reconciliation) - failed} of "
            f"{len(r.reconciliation)} hold | {len(r.invariants) - len(broken)} of "
            f"{len(r.invariants)} hold | {'PASS' if r.passed else 'FAIL'} |"
        )
    lines += ["", "## By area (largest difference, EUR)", ""]
    areas = list(AREAS)
    lines.append("| Scenario | " + " | ".join(areas) + " |")
    lines.append("|---|" + "---|" * len(areas))
    for r in results:
        cells = [f"{r.areas[a][1]:.2f}" if a in r.areas else "-" for a in areas]
        lines.append(f"| {r.slug} | " + " | ".join(cells) + " |")
    lines += ["", "## Loans and tax payments", ""]
    for r in results:
        same = "the same" if r.payments_engine == r.payments_model else "DIFFERENT"
        lines.append(f"- **{r.slug}**: {r.loans_compared} loan figures compared, "
                     f"{len(r.loan_discrepancies)} over EUR 0.01; tax payments "
                     f"({len(r.payments_model)}) {same} in both models.")  # fmt: skip
    lines += ["", "## Engine notes (warnings stated with the projection)", ""]
    for r in results:
        for note in r.notes or ["none"]:
            lines.append(f"- {r.slug}: {note}")
    lines += ["", "## Discrepancies", ""]
    found = [(r.slug, d) for r in results for d in r.discrepancies]
    found_loans = [(r.slug, d) for r in results for d in r.loan_discrepancies]
    if not found and not found_loans:
        lines.append("None: every compared value is within EUR 0.01.")
    for slug, d in found:
        lines.append(f"- {slug} {d.month} {d.key}: engine {d.engine:.2f}, model {d.model:.2f}")
    for slug, text in found_loans:
        lines.append(f"- {slug} {text}")
    return "\n".join(lines) + "\n"


def tax_payments_md(results: list[Result]) -> str:
    lines = ["# Tax payments by scenario (generated)", ""]
    for r in results:
        lines += [f"## {r.name}", ""]
        lines += [f"- {p}" for p in r.payments_model] or ["- none"]
        lines.append("")
    return "\n".join(lines)


def outputs(results: list[Result]) -> dict[str, str]:
    files = {"summary.md": summary_md(results), "tax-payments.md": tax_payments_md(results)}
    for r in results:
        files[f"{r.slug}/independent-model.csv"] = statements_csv(r.model)
        files[f"{r.slug}/engine.csv"] = statements_csv(r.engine)
        files[f"{r.slug}/comparison.csv"] = comparison_csv(r)
        files[f"{r.slug}/reconciliation.csv"] = reconciliation_csv(r)
    return files


def workbook(results: list[Result], path: Path) -> None:
    """A workbook for the reviewer: each scenario's statements from the independent model, and a
    checks sheet whose reconciliations are live Excel formulas over those figures."""
    from openpyxl import Workbook  # noqa: PLC0415 (only when writing the workbook)
    from openpyxl.utils import get_column_letter  # noqa: PLC0415

    wb = Workbook()
    for sheet in list(wb.worksheets):
        wb.remove(sheet)
    for r in results:
        ws = wb.create_sheet(r.slug[:28])
        months = r.model
        keys = [*months[0].pl, *months[0].bs, *months[0].cf]
        ws.append(["line", *(m.month.isoformat()[:7] for m in months)])
        row_of = {}
        for key in keys:
            ws.append([key, *({**m.pl, **m.bs, **m.cf}[key] for m in months)])
            row_of[key] = ws.max_row
        ws.append([])
        ws.append(["CHECKS (live formulas; each should be 0)"])

        def formula(text: str, col: int, rows: dict[str, int] = row_of) -> str:
            letter = get_column_letter(col)
            out = text
            for key, row in sorted(rows.items(), key=lambda kv: -len(kv[0])):
                out = out.replace("{" + key + "}", f"{letter}{row}")
            return out

        assets = "+".join("{" + k + "}" for k in ("BS.PPE.GROSS", "BS.PPE.ACCDEP",
                          "BS.INTANGIBLES", "BS.INVESTMENTS", "BS.INVENTORY", "BS.AR",
                          "BS.OTHER_REC", "BS.TAX_REC", "BS.CASH"))  # fmt: skip
        claims = "+".join("{" + k + "}" for k in (
            "BS.DEBT.NONCURRENT", "BS.DEBT.CURRENT", "BS.AP", "BS.OTHER_PAY", "BS.TAX_PAY",
            "BS.INCOME_TAX", "BS.DEFERRED_TAX", "BS.EQUITY.SHARE_CAPITAL",
            "BS.EQUITY.SHARE_PREMIUM", "BS.EQUITY.RETAINED"))  # fmt: skip
        checks = [
            ("Assets - (liabilities + equity)", f"=ROUND(({assets})-({claims}),2)"),
            ("Cash flow closing cash - balance sheet cash",
             "=ROUND({CF.CLOSING_CASH}-{BS.CASH},2)"),
            ("Net income - (revenue - costs - D&A - interest - tax)",
             "=ROUND({PL.NET_INCOME}-({PL.REVENUE}-{PL.COGS}-{PL.OPEX}-{PL.DA}-{PL.INTEREST}"
             "-{PL.TAX}),2)"),
            ("Operating cash flow - its parts",
             "=ROUND({CF.OPERATING}-({CF.NET_INCOME}+{CF.DA}+{CF.TAX_EXPENSE}+{CF.WC.AR}"
             "+{CF.WC.INVENTORY}+{CF.WC.AP}+{CF.TAX_PAID}),2)"),
        ]  # fmt: skip
        for label, text in checks:
            ws.append([label, *(formula(text, col) for col in range(2, len(months) + 2))])
        ws.freeze_panes = "B2"
        ws.column_dimensions["A"].width = 52
    wb.save(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if out of date or failing")
    args = parser.parse_args(argv)
    results = run_all()
    files = outputs(results)
    out = ROOT / "results"
    stale = [name for name, text in files.items()
             if not (out / name).exists() or (out / name).read_text() != text]  # fmt: skip
    if args.check:
        failed = [r.slug for r in results if not r.passed]
        if stale or failed:
            print(f"Out of date: {stale}; failing: {failed}")  # noqa: T201 (a command)
            return 1
        print(f"{len(results)} scenarios pass and the results are up to date.")  # noqa: T201
        return 0
    for name, text in files.items():
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        (out / name).write_text(text)
    workbook(results, out / "validation-workbook.xlsx")
    for r in results:
        print(  # noqa: T201 (a command)
            f"{r.slug}: {'PASS' if r.passed else 'FAIL'} ({r.compared} values, "
            f"{len(r.discrepancies)} over EUR 0.01)"
        )
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
