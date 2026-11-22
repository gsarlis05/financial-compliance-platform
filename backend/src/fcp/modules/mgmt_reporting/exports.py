"""Excel and PDF exports of a report pack (M8-3, doc 10 §9, FR-M3, AC-MR5).

Both are rendered from the pack's sections (``sections.render`` over the frozen snapshot), the
same data the API returns, so every exported figure equals the figure on screen:
- **XLSX:** a cover sheet (entity, pack, status, scope and provenance, a legend of natures), then
  one sheet per section. Each table has a header row and, under it, a **Nature** row; amounts are
  exact numbers in numeric cells; text is formula-safe (threat T9).
- **PDF:** A4 landscape; a cover page with scope and provenance; each section with its notice,
  tables and commentary; on every page a provenance footer ("Actuals as of …; ledger posting #…;
  Budget …; Forecast run …") with page numbers, and a diagonal **DRAFT** watermark until final.
"""

import io
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from xml.sax.saxutils import escape

from fcp.core.export import pdf_fonts, safe_text

Lang = Literal["en", "el"]
_TEXT = {
    "en": {
        "pack": "Management report pack", "status": "Status", "version": "Version",
        "period": "Period", "generated": "Figures taken", "nature": "Nature",
        "scope": "Scope: the figures the preparer could see when the pack was generated.",
        "hidden": "Left out (not visible to the preparer): {parts}.",
        "legend": "Natures: Actual = posted entries; Budget = approved budget; Blended = actual "
                  "months plus the budget for the rest of the year; Forecast = a forecast or "
                  "projection.",
        "provenance": "Actuals as of {end} (ledger posting #{watermark}); {budget}; {forecast}",
        "budget": "Budget {name} v{version}", "no_budget": "no budget",
        "forecast": "Forecast run {run}", "no_forecast": "no published projection",
        "page": "Page {n}", "draft": "DRAFT", "comment": "Commentary",
        "risks": "Risks", "owner": "Owner", "mitigation": "Mitigation", "none": "None.",
        "DRAFT": "Draft", "IN_REVIEW": "In review", "FINAL": "Final", "SUPERSEDED": "Superseded",
        "ACTUAL": "Actual", "BUDGET": "Budget", "BLENDED": "Blended", "FORECAST": "Forecast",
        "HYPOTHETICAL": "Hypothetical",
    },
    "el": {
        "pack": "Πακέτο αναφοράς διοίκησης", "status": "Κατάσταση", "version": "Έκδοση",
        "period": "Περίοδος", "generated": "Λήψη στοιχείων", "nature": "Φύση",
        "scope": "Εύρος: στοιχεία ορατά στον συντάκτη κατά τη δημιουργία.",
        "hidden": "Εκτός (μη ορατά στον συντάκτη): {parts}.",
        "legend": "Φύση: Πραγματικό = καταχωρημένες εγγραφές· Προϋπολογισμός = εγκεκριμένος "
                  "προϋπολογισμός· Μικτό = πραγματικοί μήνες και προϋπολογισμός υπόλοιπων "
                  "μηνών· Πρόβλεψη = πρόβλεψη ή προβολή.",
        "provenance": "Πραγματικά έως {end} (εγγραφή #{watermark})· {budget}· {forecast}",
        "budget": "Προϋπολογισμός {name} έκδ. {version}", "no_budget": "χωρίς προϋπολογισμό",
        "forecast": "Υπολογισμός πρόβλεψης {run}",
        "no_forecast": "χωρίς δημοσιευμένη προβολή",
        "page": "Σελίδα {n}", "draft": "ΠΡΟΣΧΕΔΙΟ", "comment": "Σχόλια",
        "risks": "Κίνδυνοι", "owner": "Υπεύθυνος", "mitigation": "Αντιμετώπιση", "none": "Κανένας.",
        "DRAFT": "Πρόχειρο", "IN_REVIEW": "Υπό έλεγχο", "FINAL": "Οριστικό",
        "SUPERSEDED": "Αντικαταστάθηκε",
        "ACTUAL": "Πραγματικό", "BUDGET": "Προϋπολογισμός", "BLENDED": "Μικτό",
        "FORECAST": "Πρόβλεψη", "HYPOTHETICAL": "Υποθετικό",
    },
}  # fmt: skip
AMOUNT_FORMAT = "#,##0.00;-#,##0.00;-"
# PDF layout in points and opacity, not amounts.
CELL, NOTE = 7.5, 8.5  # fcp-lint: allow-float (PDF font sizes, not amounts)
RULE, WATERMARK_ALPHA = 0.6, 0.12  # fcp-lint: allow-float (PDF line width and opacity)
WATERMARK_RED = (0.8, 0.1, 0.1)  # fcp-lint: allow-float (PDF colour, not an amount)
LABEL_SHARE = 0.3  # fcp-lint: allow-float (share of the page width for row labels)


def provenance(pack: Any, lang: Lang) -> str:
    t, blocks = _TEXT[lang], pack.snapshot["blocks"]
    budget = blocks["budget"]
    projection = blocks["projection"]
    return t["provenance"].format(
        end=pack.period_end.isoformat(), watermark=pack.watermark,
        budget=t["budget"].format(name=budget["data"]["budget_name"],
                                  version=budget["data"]["version_number"])
        if budget["status"] == "ok" else t["no_budget"],
        forecast=t["forecast"].format(run=str(projection["data"]["run_id"])[:8])
        if projection["status"] == "ok" else t["no_forecast"],
    )  # fmt: skip


def _hidden(pack: Any) -> list[str]:
    return [k for k, b in pack.snapshot["blocks"].items() if b["status"] == "denied"]


def _number(value: str | None) -> Decimal | str | None:
    """Exact amounts become numbers; anything else stays text (formula-safe)."""
    if value is None:
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return safe_text(value)


def _label(item: dict[str, Any], lang: Lang, key: str = "label") -> str:
    return str(item[f"{key}_el"] if lang == "el" else item[key])


def _column_natures(table: dict[str, Any]) -> list[str | None]:
    """The nature of each value column: the nature its cells share (None for text columns)."""
    out: list[str | None] = []
    for i in range(len(table["columns"]) - 1):
        found = {r["cells"][i]["nature"] for r in table["rows"]} - {None}
        out.append(sorted(found)[0] if len(found) == 1 else None)
    return out


# --- Excel ----------------------------------------------------------------------------------------


def to_xlsx(pack: Any, entity_name: str, rendered: list[dict[str, Any]], lang: Lang = "en", *,
            generated: datetime) -> bytes:  # fmt: skip
    from openpyxl import Workbook  # noqa: PLC0415 (only exports need openpyxl)
    from openpyxl.styles import Font  # noqa: PLC0415

    t = _TEXT[lang]
    book = Workbook()
    book.remove(book.active)  # type: ignore[arg-type]
    cover = book.create_sheet("COVER")
    hidden = _hidden(pack)
    for line in (entity_name, pack.title, t["pack"],
                 f"{t['period']}: {pack.period_start.isoformat()} - {pack.period_end.isoformat()}",
                 f"{t['status']}: {t[pack.status]} · {t['version']} {pack.version}",
                 f"{t['generated']}: {pack.generated_at.isoformat(timespec='seconds')}",
                 t["scope"], *([t["hidden"].format(parts=", ".join(hidden))] if hidden else []),
                 provenance(pack, lang), t["legend"],
                 f"{generated.isoformat(timespec='seconds')}"):  # fmt: skip
        cover.append([safe_text(line)])
    cover["A1"].font = Font(bold=True, size=13)
    cover["A2"].font = Font(bold=True)
    cover.column_dimensions["A"].width = 120
    for index, section in enumerate(rendered, start=1):
        sheet = book.create_sheet(f"{index:02d} {section['key']}"[:31])
        sheet.append([safe_text(_label(section, lang, "title"))])
        sheet["A1"].font = Font(bold=True, size=13)
        sheet.append([safe_text(provenance(pack, lang))])
        notice = section["notice_el"] if lang == "el" else section["notice"]
        for text in (notice, section["reason"]):
            if text:
                sheet.append([safe_text(text)])
        for table in section["tables"]:
            _sheet_table(sheet, table, lang, t)
        if section["risks"]:
            sheet.append([])
            sheet.append([t["risks"], t["status"], t["owner"], t["mitigation"]])
            for r in section["risks"]:
                sheet.append([safe_text(r["title"]), r["status"], safe_text(r["owner"]),
                              safe_text(r["mitigation"])])  # fmt: skip
        if section["comment"]:
            sheet.append([])
            sheet.append([t["comment"]])
            sheet.append([safe_text(section["comment"])])
        sheet.column_dimensions["A"].width = 46
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _sheet_table(sheet: Any, table: dict[str, Any], lang: Lang, t: dict[str, str]) -> None:
    from openpyxl.styles import Font  # noqa: PLC0415

    sheet.append([])
    sheet.append([safe_text(_label(table, lang, "caption"))])
    sheet.cell(sheet.max_row, 1).font = Font(bold=True)
    sheet.append([safe_text(_label(c, lang)) for c in table["columns"]])
    for cell in sheet[sheet.max_row]:
        cell.font = Font(bold=True)
    sheet.append([t["nature"], *(t.get(n, "") if n else "" for n in _column_natures(table))])
    for row in table["rows"]:
        values = [_number(c["value"]) for c in row["cells"]]
        sheet.append([safe_text(_label(row, lang)), *values])
        strong = row.get("kind") in ("heading", "subtotal", "total")
        for column, value in enumerate(values, start=2):
            cell = sheet.cell(sheet.max_row, column)
            if isinstance(value, Decimal):
                cell.number_format = AMOUNT_FORMAT
            cell.font = Font(bold=strong)
        sheet.cell(sheet.max_row, 1).font = Font(bold=strong)


# --- PDF ------------------------------------------------------------------------------------------


def _amount(value: str | None, lang: Lang) -> str:
    if value is None:
        return ""
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        return value
    text = f"{number:,.2f}"
    if lang == "el":
        thin = chr(0x2009)
        text = text.replace(",", thin).replace(".", ",").replace(thin, ".")
    return text


def to_pdf(pack: Any, entity_name: str, rendered: list[dict[str, Any]], lang: Lang = "en", *,
           generated: datetime) -> bytes:  # fmt: skip
    from reportlab.lib import colors  # noqa: PLC0415 (only exports need ReportLab)
    from reportlab.lib.pagesizes import A4, landscape  # noqa: PLC0415
    from reportlab.lib.styles import ParagraphStyle  # noqa: PLC0415
    from reportlab.lib.units import mm  # noqa: PLC0415
    from reportlab.platypus import (  # noqa: PLC0415
        Flowable,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    regular, bold = pdf_fonts()
    t = _TEXT[lang]
    styles = {
        "title": ParagraphStyle("title", fontName=bold, fontSize=16, leading=20),
        "heading": ParagraphStyle("heading", fontName=bold, fontSize=12, leading=16),
        "body": ParagraphStyle("body", fontName=regular, fontSize=9, leading=12),
        "small": ParagraphStyle("small", fontName=regular, fontSize=CELL, leading=10,
                                textColor=colors.HexColor("#555555")),
        "notice": ParagraphStyle("notice", fontName=bold, fontSize=NOTE, leading=11,
                                 textColor=colors.HexColor("#7a3e00")),
        "cell": ParagraphStyle("cell", fontName=regular, fontSize=CELL, leading=9),
    }  # fmt: skip
    footer = provenance(pack, lang)
    draft = pack.status not in {"FINAL", "SUPERSEDED"}

    def decorate(canvas: Any, doc: Any) -> None:
        width, height = doc.pagesize
        canvas.saveState()
        canvas.setFont(regular, 7)
        canvas.setFillColor(colors.HexColor("#555555"))
        canvas.drawString(14 * mm, 8 * mm, f"{entity_name} · {pack.title} · {footer}"[:180])
        canvas.drawRightString(width - 14 * mm, 8 * mm, t["page"].format(n=doc.page))
        if draft:
            canvas.setFont(bold, 90)
            canvas.setFillColor(colors.Color(*WATERMARK_RED, alpha=WATERMARK_ALPHA))
            canvas.translate(width / 2, height / 2)
            canvas.rotate(30)
            canvas.drawCentredString(0, 0, t["draft"])
        canvas.restoreState()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=14 * mm,
                            rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
                            title=pack.title, author=entity_name)  # fmt: skip
    hidden = _hidden(pack)
    story: list[Flowable] = [
        Paragraph(escape(entity_name), styles["title"]),
        Paragraph(escape(pack.title), styles["heading"]),
        Spacer(1, 3 * mm),
        Paragraph(escape(f"{t['period']}: {pack.period_start.isoformat()} - "
                         f"{pack.period_end.isoformat()}"), styles["body"]),
        Paragraph(escape(f"{t['status']}: {t[pack.status]} · {t['version']} {pack.version}"),
                  styles["body"]),
        Paragraph(escape(f"{t['generated']}: {pack.generated_at.isoformat(timespec='seconds')}"),
                  styles["body"]),
        Spacer(1, 3 * mm),
        Paragraph(escape(t["scope"]), styles["small"]),
        *([Paragraph(escape(t["hidden"].format(parts=", ".join(hidden))), styles["small"])]
          if hidden else []),
        Paragraph(escape(footer), styles["small"]),
        Paragraph(escape(t["legend"]), styles["small"]),
        Paragraph(escape(generated.isoformat(timespec="seconds")), styles["small"]),
    ]  # fmt: skip
    for section in rendered:
        story += [PageBreak(), *_pdf_section(section, lang, t, styles, doc.width)]
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


def _pdf_section(section: dict[str, Any], lang: Lang, t: dict[str, str],
                 styles: dict[str, Any], width: Any) -> list[Any]:  # fmt: skip
    from reportlab.lib.units import mm  # noqa: PLC0415
    from reportlab.platypus import Paragraph, Spacer  # noqa: PLC0415

    out: list[Any] = [Paragraph(escape(_label(section, lang, "title")), styles["heading"])]
    notice = section["notice_el"] if lang == "el" else section["notice"]
    if notice:
        out.append(Paragraph(escape(notice), styles["notice"]))
    if section["reason"]:
        out.append(Paragraph(escape(section["reason"]), styles["body"]))
    for table in section["tables"]:
        out += [Spacer(1, 3 * mm), Paragraph(escape(_label(table, lang, "caption")),
                                             styles["body"]),
                _pdf_table(table, lang, t, styles, width)]  # fmt: skip
    if section["key"] == "risks":
        out.append(Spacer(1, 3 * mm))
        if not section["risks"]:
            out.append(Paragraph(escape(t["none"]), styles["body"]))
        for r in section["risks"]:
            line = f"{r['title']} · {r['status']} · {t['owner']}: {r['owner'] or '-'}"
            out.append(Paragraph(escape(line), styles["body"]))
            if r["mitigation"]:
                out.append(Paragraph(escape(r["mitigation"]), styles["small"]))
    if section["comment"]:
        out += [
            Spacer(1, 3 * mm),
            Paragraph(escape(t["comment"]), styles["body"]),
            Paragraph(escape(section["comment"]).replace("\n", "<br/>"), styles["body"]),
        ]
    return out


def pdf_lines(table: dict[str, Any], lang: Lang) -> list[list[str]]:
    """The text of each line of a table as the PDF prints it: the header, the nature line, then
    one line per row (label and formatted figures)."""
    t = _TEXT[lang]
    header = [_label(c, lang) for c in table["columns"]]
    natures = [t["nature"], *(t.get(n, "") if n else "" for n in _column_natures(table))]
    rows = [[_label(row, lang), *(_amount(c["value"], lang) for c in row["cells"])]
            for row in table["rows"]]  # fmt: skip
    return [header, natures, *rows]


def _pdf_table(table: dict[str, Any], lang: Lang, t: dict[str, str], styles: dict[str, Any],
               width: Any) -> Any:  # fmt: skip
    from reportlab.lib import colors  # noqa: PLC0415
    from reportlab.lib.units import mm  # noqa: PLC0415
    from reportlab.platypus import Paragraph, Table, TableStyle  # noqa: PLC0415

    del t
    regular, bold = pdf_fonts()
    lines = pdf_lines(table, lang)
    count = len(table["columns"])
    data: list[list[Any]] = [
        [Paragraph(escape(x), styles["cell"]) for x in lines[0]],
        lines[1],
        *([Paragraph(escape(line[0]), styles["cell"]), *line[1:]] for line in lines[2:]),
    ]
    look: list[tuple[Any, ...]] = [
        ("FONT", (0, 0), (-1, 0), bold, CELL), ("FONT", (0, 1), (-1, -1), regular, CELL),
        ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor("#555555")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 1), (-1, 1), RULE, colors.black),
    ]  # fmt: skip
    for number, row in enumerate(table["rows"], start=2):
        if row.get("kind") in ("heading", "subtotal", "total"):
            look.append(("FONT", (1, number), (-1, number), bold, CELL))
    first = min(70 * mm, width * LABEL_SHARE)
    rest = (width - first) / max(count - 1, 1)
    grid = Table(data, colWidths=[first, *([rest] * (count - 1))], repeatRows=2)
    grid.setStyle(TableStyle(look))
    return grid
