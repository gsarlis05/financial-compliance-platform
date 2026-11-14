"""Excel export of a projection's statements (M6-6, brief §3): one sheet per statement, a nature
row above the figures (ACTUAL for the opening balance sheet, FORECAST otherwise), formula-safe text
(threat T9) and exact amounts in numeric cells. Every sheet says what it is: a projection, not
actual results, with its run, cut-over, watermark, hashes and invariant status."""

import io
from datetime import datetime
from typing import Literal

from fcp.core.export import safe_text

from .layout import STATEMENTS, name, with_totals
from .runs import Statements

Lang = Literal["en", "el"]
_TEXT = {
    "en": {"nature": "Nature", "ACTUAL": "Actual", "FORECAST": "Forecast", "line": "Line",
           "note": "Projection (forecast, not actual results). Run {run} ({status}); cut-over "
                   "{cutover}; postings up to #{watermark}; inputs {input_hash}; outputs "
                   "{output_hash}; generated {generated}.",
           "opening": "Opening (actual)"},
    "el": {"nature": "Φύση", "ACTUAL": "Πραγματικό", "FORECAST": "Πρόβλεψη", "line": "Γραμμή",
           "note": "Πρόβλεψη (όχι πραγματικά αποτελέσματα). Υπολογισμός {run} ({status}); "
                   "ημερομηνία αποκοπής {cutover}; εγγραφές έως #{watermark}; είσοδοι "
                   "{input_hash}; έξοδοι {output_hash}; δημιουργία {generated}.",
           "opening": "Έναρξη (πραγματικό)"},
}  # fmt: skip


def _heading(start: str, end: str, granularity: str) -> str:
    if granularity == "MONTH":
        return start[:7]
    return f"{start} - {end}"


def to_xlsx(s: Statements, entity_name: str, granularity: str, lang: Lang = "en", *,
            generated: datetime) -> bytes:  # fmt: skip
    from openpyxl import Workbook  # noqa: PLC0415 (only exports need openpyxl)
    from openpyxl.styles import Alignment, Font  # noqa: PLC0415

    t = _TEXT[lang]
    rows = with_totals(s.rows)
    note = t["note"].format(
        run=s.run.id, status=s.run.status, cutover=s.run.as_of_date.isoformat(),
        watermark=s.run.actuals_watermark, input_hash=s.run.input_hash[:12],
        output_hash=s.run.output_hash[:12], generated=generated.isoformat(timespec="seconds"),
    )  # fmt: skip
    book = Workbook()
    book.remove(book.active)  # type: ignore[arg-type]
    amount_format = "#,##0.00;-#,##0.00;-"
    for code, layout in STATEMENTS:
        columns = [(i, c) for i, c in enumerate(s.columns)
                   if code == "BS" or c.nature != "ACTUAL"]  # fmt: skip
        sheet = book.create_sheet(code)
        sheet.append([safe_text(entity_name)])
        sheet.append([name(code, lang)])
        sheet["A1"].font = Font(bold=True, size=13)
        sheet["A2"].font = Font(bold=True)
        sheet.append([safe_text(note)])
        sheet.append([])
        sheet.append([t["line"], *(t["opening"] if c.nature == "ACTUAL"
                                   else _heading(str(c.start), str(c.end), granularity)
                                   for _, c in columns)])  # fmt: skip
        sheet.append([t["nature"], *(t[c.nature] for _, c in columns)])
        for cell in (*sheet[5], *sheet[6]):
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="right")
        for key, kind in layout:
            values = rows.get(key, [])
            cells = [values[i] if i < len(values) else None for i, _ in columns]
            sheet.append([safe_text(name(key, lang)), *cells])
            excel_row = sheet.max_row
            bold = kind != "line"
            sheet.cell(excel_row, 1).font = Font(bold=bold)
            for column in range(2, len(columns) + 2):
                cell = sheet.cell(excel_row, column)
                cell.number_format = amount_format
                cell.font = Font(bold=bold)
        sheet.column_dimensions["A"].width = 46
        sheet.freeze_panes = "B7"
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
