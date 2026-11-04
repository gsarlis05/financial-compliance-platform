"""Exports of the basic statements: CSV, XLSX and PDF (M2-8).

Text cells are formula-safe (threat T9). Amounts are exact decimals: numeric cells in XLSX, plain
``1234.56`` in CSV, and locale-formatted in PDF. Every export states what it is (management
statements, not statutory), the period, the taxonomy and the posting watermark it includes.
"""

import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from xml.sax.saxutils import escape

from fcp.core.export import pdf_fonts, safe_text

from .statements import Row, Statement, Statements

Lang = Literal["en", "el"]

_TEXT = {
    "en": {
        "current": "Current",
        "comparative": "Comparative",
        "statement": "Statement",
        "code": "Code",
        "row": "Row",
        "kind": "Kind",
        "note": "Management statements (not statutory). Figures include postings up to "
        "#{watermark}; taxonomy {taxonomy}; generated {generated}.",
        "to": "to",
        "at": "at",
    },
    "el": {
        "current": "Τρέχουσα",
        "comparative": "Συγκριτική",
        "statement": "Κατάσταση",
        "code": "Κωδικός",
        "row": "Γραμμή",
        "kind": "Είδος",
        "note": "Διοικητικές καταστάσεις (όχι καταστατικές). Περιλαμβάνουν καταχωρίσεις έως "
        "#{watermark}· ταξινόμηση {taxonomy}· δημιουργήθηκε {generated}.",
        "to": "έως",
        "at": "στις",
    },
}


def _name(row: Row | Statement, lang: Lang) -> str:
    return row.name_el if lang == "el" and row.name_el else row.name


def _period(s: Statements, lang: Lang, *, comparative: bool) -> str:
    period = s.comparative if comparative else s.current
    if period is None:
        return ""
    return f"{period.date_from.isoformat()} {_TEXT[lang]['to']} {period.date_to.isoformat()}"


def _note(s: Statements, lang: Lang, generated: datetime) -> str:
    return _TEXT[lang]["note"].format(
        watermark=s.watermark,
        taxonomy=s.taxonomy,
        generated=generated.isoformat(timespec="seconds"),
    )


def _plain(value: Decimal | None) -> str:
    return "" if value is None else f"{value:.2f}"


# --- CSV ------------------------------------------------------------------------------------------


def to_csv(s: Statements, lang: Lang = "en") -> str:
    t = _TEXT[lang]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    header = [
        t["statement"],
        t["kind"],
        t["code"],
        t["row"],
        f"{t['current']} ({_period(s, lang, comparative=False)})",
    ]
    if s.comparative:
        header.append(f"{t['comparative']} ({_period(s, lang, comparative=True)})")
    writer.writerow(header)
    for statement in s.all:
        for row in statement.rows:
            cells = [
                statement.kind,
                row.kind,
                safe_text(row.code),
                safe_text(_name(row, lang)),
                _plain(row.current),
            ]
            if s.comparative:
                cells.append(_plain(row.comparative))
            writer.writerow(cells)
    return out.getvalue()


# --- XLSX -----------------------------------------------------------------------------------------


def to_xlsx(s: Statements, lang: Lang = "en", *, generated: datetime) -> bytes:
    from openpyxl import Workbook  # noqa: PLC0415 (only exports need openpyxl)
    from openpyxl.styles import Alignment, Font  # noqa: PLC0415

    t = _TEXT[lang]
    book = Workbook()
    book.remove(book.active)  # type: ignore[arg-type]
    amount_format = "#,##0.00;-#,##0.00;-"
    for statement in s.all:
        sheet = book.create_sheet(statement.kind)
        sheet.append([safe_text(s.entity_name)])
        sheet.append([_name(statement, lang)])
        sheet["A1"].font = Font(bold=True, size=13)
        sheet["A2"].font = Font(bold=True)
        sheet.append([_note(s, lang, generated)])
        sheet.append([])
        header = ["", f"{t['current']}\n{_period(s, lang, comparative=False)}"]
        if s.comparative:
            header.append(f"{t['comparative']}\n{_period(s, lang, comparative=True)}")
        sheet.append(header)
        for cell in sheet[5]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(wrap_text=True, horizontal="right")
        for row in statement.rows:
            values: list[object] = [safe_text(_name(row, lang)), row.current]
            if s.comparative:
                values.append(row.comparative)
            sheet.append(values)
            excel_row = sheet.max_row
            bold = row.kind in ("heading", "subtotal", "total")
            sheet.cell(excel_row, 1).font = Font(bold=bold)
            sheet.cell(excel_row, 1).alignment = Alignment(indent=1 if row.kind == "line" else 0)
            for column in range(2, len(values) + 1):
                cell = sheet.cell(excel_row, column)
                cell.number_format = amount_format
                cell.font = Font(bold=bold)
        sheet.column_dimensions["A"].width = 62
        sheet.column_dimensions["B"].width = 20
        sheet.column_dimensions["C"].width = 20
        sheet.freeze_panes = "B6"
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


# --- PDF ------------------------------------------------------------------------------------------


# Page layout in points. ReportLab takes floats; these are sizes, never amounts.
SMALL, SMALL_LEADING = 7.5, 9.5  # fcp-lint: allow-float (PDF layout, not an amount)
BODY, BODY_LEADING = 8.5, 10.5  # fcp-lint: allow-float (PDF layout, not an amount)
RULE_THIN, RULE, RULE_THICK = 0.4, 0.6, 0.8  # fcp-lint: allow-float (PDF layout, not an amount)


def _amount(value: Decimal | None, lang: Lang) -> str:
    if value is None:
        return ""
    text = f"{value:,.2f}"
    if lang == "el":
        text = text.replace(",", "\u2009").replace(".", ",").replace("\u2009", ".")
    return text


def to_pdf(s: Statements, lang: Lang = "en", *, generated: datetime) -> bytes:
    from reportlab.lib import colors  # noqa: PLC0415 (only exports need ReportLab)
    from reportlab.lib.pagesizes import A4  # noqa: PLC0415
    from reportlab.lib.styles import ParagraphStyle  # noqa: PLC0415
    from reportlab.lib.units import mm  # noqa: PLC0415
    from reportlab.platypus import (  # noqa: PLC0415
        Flowable,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    regular, bold = pdf_fonts()
    t = _TEXT[lang]
    title = ParagraphStyle("title", fontName=bold, fontSize=14, leading=18)
    subtitle = ParagraphStyle("subtitle", fontName=bold, fontSize=11, leading=14)
    small = ParagraphStyle(
        "small",
        fontName=regular,
        fontSize=SMALL,
        leading=SMALL_LEADING,
        textColor=colors.HexColor("#555555"),
    )
    cell = ParagraphStyle("cell", fontName=regular, fontSize=BODY, leading=BODY_LEADING)
    cell_bold = ParagraphStyle("cell_bold", parent=cell, fontName=bold)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"{s.entity_name} {s.current.date_to.isoformat()}",
    )
    story: list[Flowable] = []
    for index, statement in enumerate(s.all):
        if index:
            story.append(PageBreak())
        story += [
            Paragraph(escape(s.entity_name), title),
            Paragraph(escape(_name(statement, lang)), subtitle),
            Paragraph(escape(_note(s, lang, generated)), small),
            Spacer(1, 4 * mm),
        ]
        header = ["", f"{t['current']}\n{_period(s, lang, comparative=False)}"]
        if s.comparative:
            header.append(f"{t['comparative']}\n{_period(s, lang, comparative=True)}")
        data: list[list[object]] = [list(header)]
        styles: list[tuple[Any, ...]] = [
            ("FONT", (0, 0), (-1, 0), bold, 8),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), RULE, colors.black),
            ("FONT", (1, 1), (-1, -1), regular, BODY),
        ]
        for number, row in enumerate(statement.rows, start=1):
            strong = row.kind in ("heading", "subtotal", "total")
            indent = "\u2003" if row.kind == "line" else ""
            values: list[object] = [
                Paragraph(indent + escape(_name(row, lang)), cell_bold if strong else cell),
                _amount(row.current, lang),
            ]
            if s.comparative:
                values.append(_amount(row.comparative, lang))
            data.append(values)
            if strong:
                styles.append(("FONT", (1, number), (-1, number), bold, BODY))
            if row.kind in ("subtotal", "total"):
                styles.append(("LINEABOVE", (1, number), (-1, number), RULE_THIN, colors.black))
            if row.kind == "total":
                styles.append(("LINEBELOW", (1, number), (-1, number), RULE_THICK, colors.black))
        widths = [100 * mm, 37 * mm, 37 * mm][: len(header)]
        table = Table(data, colWidths=widths, repeatRows=1)
        table.setStyle(TableStyle(styles))
        story.append(table)
    doc.build(story)
    return buffer.getvalue()
