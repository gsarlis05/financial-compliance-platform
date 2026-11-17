"""The sections of a report pack (M8-2, doc 10 §9, FR-M1, FR-M2, AC-MR4), rendered from its frozen
snapshot, its commentary and its risks. Pure functions: the same snapshot, notes and choices always
render the same sections, which the screen and the exports (M8-3) both use.

Each section is ``{key, title, title_el, status, reason, notice, tables, comment, risks}``. A table
has columns and rows; every cell is ``{"value": exact decimal string or text or None, "nature":
ACTUAL | BUDGET | BLENDED | FORECAST | HYPOTHETICAL | None}``, so the nature of every figure stays
visible (FR-D2). Nothing is computed here except differences of two figures of the same snapshot.

Comparison columns (``pack.columns``): ``actual`` is always shown; ``budget`` (current approved),
``original_budget``, ``prior_year`` and ``variance`` add columns; ``forecast`` adds the full-year
outlook (actual months plus the budget for the rest of the year) to budget performance.
"""

from decimal import Decimal
from typing import Any

from fcp.modules.projections.api import line_name

PENDING = ("Pending professional review: the projection engine has not been independently "
           "validated. Use these figures as estimates, not certified figures.")  # fmt: skip
PENDING_EL = ("Εκκρεμεί επαγγελματικός έλεγχος: το μοντέλο προβολών δεν έχει επικυρωθεί "
              "ανεξάρτητα. Πρόκειται περί εκτιμήσεων, όχι πιστοποιημένων στοιχείων.")  # fmt: skip
TITLES = {
    "overview": ("Executive overview", "Συνοπτική εικόνα"),
    "profitability": ("Revenue and profitability", "Έσοδα και κερδοφορία"),
    "cash": ("Cash flow", "Ταμειακές ροές"),
    "working_capital": ("Financial position and working capital",
                        "Οικονομική θέση και κεφάλαιο κίνησης"),
    "budget": ("Budget performance", "Απόδοση προϋπολογισμού"),
    "kpis": ("KPI scorecard", "Δείκτες απόδοσης"),
    "forecast": ("Forecast", "Πρόβλεψη"),
    "risks": ("Risks", "Κίνδυνοι"),
    "goals": ("Goal progress", "Πρόοδος στόχων"),
    "commentary": ("Commentary", "Σχόλια"),
}  # fmt: skip
LABELS = {
    "line": ("Line", "Γραμμή"), "actual": ("Actual", "Πραγματικό"),
    "prior_year": ("Prior year", "Προηγούμενο έτος"), "change": ("Change", "Μεταβολή"),
    "budget": ("Budget", "Προϋπολογισμός"),
    "original_budget": ("Original budget", "Αρχικός προϋπολογισμός"),
    "variance": ("Variance", "Απόκλιση"), "variance_pct": ("Variance %", "Απόκλιση %"),
    "assessment": ("Assessment", "Αξιολόγηση"), "explanation": ("Explanation", "Εξήγηση"),
    "value": ("Value", "Τιμή"), "nature": ("Nature", "Φύση"), "note": ("Note", "Σημείωση"),
    "target": ("Target", "Στόχος"), "projected": ("Likely outcome", "Πιθανή έκβαση"),
    "status": ("Status", "Κατάσταση"), "as_of": ("As of", "Έως"), "kpi": ("KPI", "Δείκτης"),
    "goal": ("Goal", "Στόχος"), "closing": ("Closing cash", "Ταμείο λήξης"),
    "minimum": ("Minimum cash", "Ελάχιστο ταμείο"),
}  # fmt: skip
VIEW_OF = {"MONTH": "MONTH", "QUARTER": "QTD", "YEAR": "YTD"}
VIEWS = ("MONTH", "QTD", "YTD", "FULL_YEAR")
VIEW_NAMES = {"MONTH": ("Month", "Μήνας"), "QTD": ("Quarter to date", "Τρίμηνο έως σήμερα"),
              "YTD": ("Year to date", "Έτος έως σήμερα"),
              "FULL_YEAR": ("Full-year outlook", "Εκτίμηση έτους")}  # fmt: skip
PROJECTED = ("PL.REVENUE", "PL.EBITDA", "PL.NET_INCOME", "CF.NET_CHANGE", "BS.CASH")
WORKING_CAPITAL_KPIS = ("DSO", "DIO", "DPO", "CASH_CONVERSION_CYCLE", "CURRENT_RATIO",
                        "QUICK_RATIO")  # fmt: skip


def _cell(value: str | None, nature: str | None) -> dict[str, Any]:
    return {"value": value, "nature": nature}


def _col(key: str, label: tuple[str, str] | None = None) -> dict[str, str]:
    en, el = label or LABELS[key]
    return {"key": key, "label": en, "label_el": el}


def _diff(a: str | None, b: str | None) -> str | None:
    return None if a is None or b is None else f"{Decimal(a) - Decimal(b):.2f}"


def _table(caption: tuple[str, str], columns: list[dict[str, str]],
           rows: list[dict[str, Any]]) -> dict[str, Any]:  # fmt: skip
    return {"caption": caption[0], "caption_el": caption[1], "columns": columns, "rows": rows}


# --- statements (profitability, cash, working capital, overview) ----------------------------------


def _statement(data: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(s for s in data["statements"] if s["kind"] == kind)


def _statement_table(statement: dict[str, Any], columns: list[str],
                     keep: Any = None) -> dict[str, Any]:  # fmt: skip
    py, change = "prior_year" in columns, "variance" in columns
    cols = [_col("line"), _col("actual")]
    cols += [_col("prior_year")] if py else []
    cols += [_col("change")] if py and change else []
    rows = []
    for r in statement["rows"]:
        if keep is not None and not keep(r):
            continue
        cells = [_cell(r["current"], "ACTUAL")]
        cells += [_cell(r["comparative"], "ACTUAL")] if py else []
        cells += [_cell(_diff(r["current"], r["comparative"]), "ACTUAL")] if py and change else []
        rows.append({"key": r["code"], "label": r["name"], "label_el": r["name_el"],
                     "kind": r["kind"], "cells": cells})  # fmt: skip
    return _table((statement["name"], statement["name_el"]), cols, rows)


# --- budget performance ---------------------------------------------------------------------------


def _report(data: dict[str, Any], view: str, comparison: str) -> dict[str, Any] | None:
    return next((r for r in data["reports"]
                 if (r["view"], r["comparison"]) == (view, comparison)), None)  # fmt: skip


def _key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (row["taxonomy_code"], row["account_id"], row["dimension_value_id"])


def _verdict(favourable: bool | None) -> tuple[str | None, str | None]:
    if favourable is None:
        return None, None
    return ("Favourable", "Ευνοϊκή") if favourable else ("Unfavourable", "Δυσμενής")


def names_of(blocks: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """Line names by taxonomy code, from the snapshot's own statements."""
    st = blocks["statements"]
    if st["status"] != "ok":
        return {}
    return {r["code"]: (r["name"], r["name_el"]) for s in st["data"]["statements"]
            for r in s["rows"]}  # fmt: skip


def budget_table(data: dict[str, Any], view: str, columns: list[str], lang: str = "en",
                 names: dict[str, tuple[str, str]] | None = None) -> dict[str, Any]:  # fmt: skip
    """One period view of the variance report: actual against the current budget, with the
    original budget and the prior year beside it when chosen."""
    main = _report(data, view, "ACTUAL_VS_BUDGET") or {"rows": []}
    original = {_key(r): r for r in (_report(data, view, "CURRENT_VS_ORIGINAL") or {"rows": []})
                ["rows"]}  # fmt: skip
    prior = {_key(r): r for r in (_report(data, view, "ACTUAL_VS_PRIOR_YEAR") or {"rows": []})
             ["rows"]}  # fmt: skip
    shown = [c for c in ("budget", "original_budget", "prior_year", "variance") if c in columns]
    cols = [_col("line"), _col("actual"), *(_col(c) for c in shown)]
    if "variance" in shown:
        cols += [_col("variance_pct"), _col("assessment"), _col("explanation")]
    rows = []
    for r in main["rows"]:
        cells = [_cell(r["subject"], r["subject_nature"])]
        if "budget" in shown:
            cells.append(_cell(r["comparison"], r["comparison_nature"]))
        if "original_budget" in shown:
            o = original.get(_key(r))
            cells.append(_cell(o["comparison"] if o else None, "BUDGET"))
        if "prior_year" in shown:
            p = prior.get(_key(r))
            cells.append(_cell(p["comparison"] if p else None, "ACTUAL"))
        if "variance" in shown:
            verdict = _verdict(r["favourable"])
            cells += [_cell(r["variance"], r["subject_nature"]), _cell(r["percent"], None),
                      _cell(verdict[0 if lang == "en" else 1], None),
                      _cell(r["explanation"], None)]  # fmt: skip
        code = r["taxonomy_code"] or r["account_id"] or ""
        en, el = (names or {}).get(code, (code, code))
        rows.append({"key": code, "label": en, "label_el": el,
                     "kind": "line", "requires_explanation": r["requires_explanation"],
                     "cells": cells})  # fmt: skip
    return _table(VIEW_NAMES[view], cols, rows)


def budget_views(period_kind: str, columns: list[str]) -> list[str]:
    first = VIEWS.index(VIEW_OF[period_kind])
    return [v for v in VIEWS[first:] if v != "FULL_YEAR" or "forecast" in columns]


# --- sections -------------------------------------------------------------------------------------


def _section(key: str, block: dict[str, Any] | None = None) -> dict[str, Any]:
    title = TITLES[key]
    status, reason = ("ok", "") if block is None else (block["status"], block["reason"])
    return {"key": key, "title": title[0], "title_el": title[1], "status": status,
            "reason": reason, "notice": "", "notice_el": "", "tables": [], "comment": None,
            "risks": []}  # fmt: skip


def _kpi_table(values: list[dict[str, Any]], caption: tuple[str, str]) -> dict[str, Any]:
    rows = [{"key": v["key"], "label": v["name"], "label_el": v["name_el"], "kind": "line",
             "display": v["display"],
             "cells": [_cell(v["value"], v["nature"]), _cell(v["nm_reason"] or None, None)]}
            for v in values]  # fmt: skip
    return _table(caption, [_col("kpi"), _col("value"), _col("note")], rows)


def render(pack: Any, comments: dict[str, str], risks: list[dict[str, Any]],
           lang: str = "en") -> list[dict[str, Any]]:  # fmt: skip
    """Every chosen section of the pack, in the chosen order."""
    blocks = pack.snapshot["blocks"]
    columns: list[str] = list(pack.columns)
    out = []
    for key in pack.sections:
        s = _build(key, blocks, columns, pack.period_kind, risks, lang)
        s["comment"] = comments.get(key) or None
        out.append(s)
    return out


def _statements_section(key: str, blocks: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    statements = blocks["statements"]
    s = _section(key, statements)
    if statements["status"] != "ok":
        return s
    data = statements["data"]
    if key == "overview":
        s["tables"] = [
            _statement_table(_statement(data, "PL"), columns,
                             lambda r: r["kind"] in ("subtotal", "total")),
            _statement_table(_statement(data, "BS"), columns, lambda r: r["kind"] == "total"),
        ]  # fmt: skip
    elif key == "profitability":
        s["tables"] = [_statement_table(_statement(data, "PL"), columns)]
    elif key == "cash":
        s["tables"] = [_statement_table(_statement(data, "CF"), columns), *_cash(blocks)]
    else:
        s["tables"] = [_statement_table(_statement(data, "BS"), columns), *_wc_kpis(blocks)]
    return s


def _budget_section(blocks: dict[str, Any], columns: list[str], period_kind: str,
                    lang: str) -> dict[str, Any]:  # fmt: skip
    s = _section("budget", blocks["budget"])
    if s["status"] == "ok":
        data, names = blocks["budget"]["data"], names_of(blocks)
        s["tables"] = [budget_table(data, v, columns, lang, names)
                       for v in budget_views(period_kind, columns)]  # fmt: skip
    return s


def _kpis_section(blocks: dict[str, Any]) -> dict[str, Any]:
    s = _section("kpis", blocks["kpis"])
    if s["status"] == "ok":
        s["tables"] = [_kpi_table(blocks["kpis"]["data"]["values"], TITLES["kpis"])]
    return s


def _notes_section(key: str, risks: list[dict[str, Any]]) -> dict[str, Any]:
    s = _section(key)
    if key == "risks":
        s["risks"] = risks
    return s


def _build(key: str, blocks: dict[str, Any], columns: list[str], period_kind: str,
           risks: list[dict[str, Any]], lang: str) -> dict[str, Any]:  # fmt: skip
    if key in ("overview", "profitability", "cash", "working_capital"):
        return _statements_section(key, blocks, columns)
    builders = {
        "budget": lambda: _budget_section(blocks, columns, period_kind, lang),
        "kpis": lambda: _kpis_section(blocks),
        "forecast": lambda: _forecast(blocks["projection"]),
        "goals": lambda: _goals(blocks["goals"]),
    }
    build = builders.get(key)
    return build() if build else _notes_section(key, risks)


def _cash(blocks: dict[str, Any]) -> list[dict[str, Any]]:
    cash = blocks["cash"]
    if cash["status"] != "ok":
        return []
    weeks = cash["data"]["weeks"]
    cols = [_col("line"), *({"key": w["start"], "label": w["label"], "label_el": w["label"]}
                            for w in weeks)]  # fmt: skip
    rows = [
        {
            "key": k,
            "label": LABELS[k][0],
            "label_el": LABELS[k][1],
            "kind": "line",
            "cells": [_cell(w[k], "FORECAST") for w in weeks],
        }
        for k in ("closing", "minimum")
    ]
    return [_table(("13-week cash forecast", "Πρόβλεψη ταμείου 13 εβδομάδων"), cols, rows)]


def _wc_kpis(blocks: dict[str, Any]) -> list[dict[str, Any]]:
    kpis = blocks["kpis"]
    if kpis["status"] != "ok":
        return []
    chosen = [v for v in kpis["data"]["values"] if v["key"] in WORKING_CAPITAL_KPIS]
    return [_kpi_table(chosen, ("Working-capital KPIs", "Δείκτες κεφαλαίου κίνησης"))]


def _forecast(block: dict[str, Any]) -> dict[str, Any]:
    s = _section("forecast", block)
    if block["status"] != "ok":
        return s
    data = block["data"]
    s["notice"], s["notice_el"] = PENDING, PENDING_EL
    cols = [_col("line"), *({"key": m, "label": m[:7], "label_el": m[:7]}
                            for m in data["months"])]  # fmt: skip
    rows = [{"key": k, "label": line_name(k, "en"), "label_el": line_name(k, "el"),
             "kind": "line", "cells": [_cell(v, "FORECAST") for v in data["rows"][k]]}
            for k in PROJECTED]  # fmt: skip
    s["tables"] = [_table(("Published projection", "Δημοσιευμένη προβολή"), cols, rows)]
    return s


def _goals(block: dict[str, Any]) -> dict[str, Any]:
    s = _section("goals", block)
    if block["status"] != "ok":
        return s
    cols = [_col("goal"), _col("target"), _col("projected"), _col("status"), _col("as_of")]
    rows = [{"key": x["id"], "label": x["name"], "label_el": x["name"], "kind": "line",
             "display": x["display"],
             "cells": [_cell(x["target"], None), _cell(x["projected"], "FORECAST"),
                       _cell(x["status"], None), _cell(x["as_of"], None)]}
            for x in block["data"]["goals"]]  # fmt: skip
    s["tables"] = [_table(TITLES["goals"], cols, rows)]
    return s
