"""Excel export of a scenario comparison (M7-7, brief §3): one sheet per statement with base,
scenario and difference for each period, a nature row above the figures (ACTUAL for the opening
balance sheet, HYPOTHETICAL for the scenario), a sheet with the change by override, formula-safe
text (threat T9) and exact amounts in numeric cells. Every sheet says what it is: a hypothetical
scenario, not actual results and not an approved forecast."""

import io
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fcp.core import reviews
from fcp.core.export import safe_text
from fcp.modules.projections.api import STATEMENT_LAYOUT, line_name, with_totals

from .runs import Comparison

Lang = Literal["en", "el"]
_TEXT = {
    "en": {"nature": "Nature", "ACTUAL": "Actual", "HYPOTHETICAL": "Hypothetical", "line": "Line",
           "base": "Base", "scenario": "Scenario", "difference": "Difference",
           "opening": "Opening (actual)", "effects": "Change by override", "total": "Total change",
           "IS": "Scenario income statement", "BS": "Scenario balance sheet",
           "CF": "Scenario cash flow statement",
           "note": "Scenario {name} (hypothetical: not actual results and not an approved "
                   "forecast). Base: {base} v{version} ({status}). {engine} Postings up to "
                   "#{watermark}; invariants {valid}; generated {generated}.",
           "ok": "hold", "failed": "FAILED"},
    "el": {"nature": "Φύση", "ACTUAL": "Πραγματικό", "HYPOTHETICAL": "Υποθετικό", "line": "Γραμμή",
           "base": "Βάση", "scenario": "Σενάριο", "difference": "Διαφορά",
           "opening": "Έναρξη (πραγματικό)", "effects": "Μεταβολή ανά παραδοχή",
           "total": "Συνολική μεταβολή",
           "IS": "Κατάσταση αποτελεσμάτων σεναρίου", "BS": "Κατάσταση οικονομικής θέσης σεναρίου",
           "CF": "Κατάσταση ταμειακών ροών σεναρίου",
           "note": "Σενάριο {name} (υποθετικό: όχι πραγματικά αποτελέσματα ούτε εγκεκριμένη "
                   "πρόβλεψη). Βάση: {base} έκδ. {version} ({status}). Εκκρεμεί ανεξάρτητος "
                   "επαγγελματικός έλεγχος του μοντέλου προβολών, χωρίς πιστοποίηση. Εγγραφές "
                   "έως #{watermark}; έλεγχοι {valid}; δημιουργία {generated}.",
           "ok": "εντάξει", "failed": "ΑΠΕΤΥΧΑΝ"},
}  # fmt: skip
HEADLINE_NAMES = {
    "BS.CASH": ("Closing cash", "Ταμείο λήξης"), "BS.DEBT": ("Closing debt", "Δανεισμός λήξης"),
}  # fmt: skip


def _heading(start: str, end: str, granularity: str) -> str:
    return start[:7] if granularity == "MONTH" else f"{start} - {end}"


def _difference(b: Decimal | None, s: Decimal | None) -> Decimal | None:
    return None if b is None or s is None else s - b


AMOUNT = "#,##0.00;-#,##0.00;-"


def _preamble(sheet: Any, entity_name: str, title: str, note: str) -> None:
    from openpyxl.styles import Font  # noqa: PLC0415 (only exports need openpyxl)

    sheet.append([safe_text(entity_name)])
    sheet.append([safe_text(title)])
    sheet["A1"].font = Font(bold=True, size=13)
    sheet["A2"].font = Font(bold=True)
    sheet.append([safe_text(note)])
    sheet.append([])


def _statement(sheet: Any, c: Comparison, statement: tuple[str, Any], *, granularity: str,
               lang: Lang, rows: tuple[dict[str, list[Decimal | None]], ...]) -> None:  # fmt: skip
    from openpyxl.styles import Alignment, Font  # noqa: PLC0415

    t = _TEXT[lang]
    code, layout = statement
    base, scen = rows
    columns = [(i, x) for i, x in enumerate(c.columns) if code == "BS" or x.nature != "ACTUAL"]
    heads: list[str] = [t["line"]]
    kinds: list[str] = [""]
    natures: list[str] = [t["nature"]]
    for _, x in columns:
        period = (t["opening"] if x.nature == "ACTUAL"
                  else _heading(str(x.start), str(x.end), granularity))  # fmt: skip
        heads += [period, "", ""]
        kinds += [t["base"], t["scenario"], t["difference"]]
        natures += [t[x.nature]] * 3
    for row in (heads, kinds, natures):
        sheet.append(row)
    for cell in (*sheet[5], *sheet[6], *sheet[7]):
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="right")
    for key, kind in layout:
        b, s = base.get(key, []), scen.get(key, [])
        cells: list[Decimal | None] = []
        for i, _ in columns:
            bv = b[i] if i < len(b) else None
            sv = s[i] if i < len(s) else None
            cells += [bv, sv, _difference(bv, sv)]
        sheet.append([safe_text(line_name(key, lang)), *cells])
        bold = Font(bold=kind != "line")
        sheet.cell(sheet.max_row, 1).font = bold
        for column in range(2, len(cells) + 2):
            cell = sheet.cell(sheet.max_row, column)
            cell.number_format = AMOUNT
            cell.font = bold
    sheet.column_dimensions["A"].width = 46
    sheet.freeze_panes = "B8"


def _changes(sheet: Any, c: Comparison, lang: Lang) -> None:
    from openpyxl.styles import Font  # noqa: PLC0415

    t = _TEXT[lang]
    heads = list(c.effects[-1].changes) if c.effects else []
    sheet.append(["#", "", *(_headline(h, lang) for h in heads)])
    for cell in sheet[5]:
        cell.font = Font(bold=True)
    for e in c.effects:
        label = t["total"] if e.override_id is None else e.label
        sheet.append([e.seq, safe_text(label), *(e.changes[h] for h in heads)])
        for column in range(3, len(heads) + 3):
            sheet.cell(sheet.max_row, column).number_format = AMOUNT
        if e.override_id is None:
            for cell in sheet[sheet.max_row]:
                cell.font = Font(bold=True)
    sheet.column_dimensions["B"].width = 46


def to_xlsx(c: Comparison, entity_name: str, granularity: str, lang: Lang = "en", *,
            generated: datetime) -> bytes:  # fmt: skip
    from openpyxl import Workbook  # noqa: PLC0415 (only exports need openpyxl)

    t = _TEXT[lang]
    rows = (with_totals({r.key: r.base for r in c.rows}),
            with_totals({r.key: r.scenario for r in c.rows}))  # fmt: skip
    note = t["note"].format(
        name=c.scenario.name, base=c.base.name, version=c.base.version, status=c.base.status,
        watermark=c.watermark, valid=t["ok"] if c.valid else t["failed"],
        generated=generated.isoformat(timespec="seconds"), engine=reviews.engine_note(lang),
    )  # fmt: skip
    book = Workbook()
    book.remove(book.active)  # type: ignore[arg-type]
    for statement in STATEMENT_LAYOUT:
        sheet = book.create_sheet(statement[0])
        _preamble(sheet, entity_name, t[statement[0]], note)
        _statement(sheet, c, statement, granularity=granularity, lang=lang, rows=rows)
    sheet = book.create_sheet("CHANGES")
    _preamble(sheet, entity_name, t["effects"], note)
    _changes(sheet, c, lang)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _headline(key: str, lang: Lang) -> str:
    if key in HEADLINE_NAMES:
        return HEADLINE_NAMES[key][0 if lang == "en" else 1]
    return line_name(key, lang)
