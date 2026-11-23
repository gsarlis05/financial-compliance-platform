"""Excel and PDF of a VAT period report (V1-2), from its frozen snapshot only.

Both show the same figures as the screen: the return's boxes (V1-2c), the totals, the figures by
VAT code, the VAT accounts, the checks and every line with its box contributions. A report that
is not signed off says DRAFT. Text from the books is made formula-safe in Excel (threat T9).
"""

import io
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from xml.sax.saxutils import escape

from fcp.core.export import pdf_fonts, safe_text

Lang = Literal["en", "el"]
RULE = 0.5  # fcp-lint: allow-float (PDF line width in points, layout only)
_TEXT: dict[str, dict[str, str]] = {
    "en": {
        "title": "VAT report",
        "period": "VAT period",
        "status": "Status",
        "version": "Version",
        "generated": "Figures taken",
        "watermark": "ledger posting",
        "draft": "DRAFT",
        "DRAFT": "Draft",
        "SIGNED_OFF": "Signed off",
        "FILED": "Filed",
        "SUPERSEDED": "Superseded",
        "self": "self-approved (one-person workspace)",
        "filed": "Filed on {on}, reference {ref}",
        "due": "Due date (entered): {due}",
        "totals": "Totals",
        "sales_base": "Sales: taxable amounts",
        "sales_vat": "Sales: output VAT",
        "purchase_base": "Purchases: taxable amounts",
        "purchase_vat": "Purchases: input VAT",
        "net": "Net VAT",
        "PAYABLE": "payable",
        "REFUNDABLE": "refundable",
        "NIL": "nil",
        "codes": "By VAT code",
        "code": "Code",
        "rate": "Rate",
        "expected": "At the code's rate",
        "unverified": "VAT codes not yet verified by a tax professional: {codes}.",
        "accounts": "VAT accounts",
        "account": "Account",
        "role": "Role",
        "vat": "Period VAT",
        "settled": "Settlements",
        "checks": "Checks",
        "none": "No exceptions.",
        "lines": "Lines",
        "date": "Date",
        "entry": "Entry",
        "kind": "Kind",
        "amount": "Amount",
        "description": "Description",
        "counterparty": "Counterparty",
        "reference": "Reference",
        "return": "VAT return",
        "box": "Box",
        "item": "Item",
        "rounding": "Rounding",
        "rules": "Box rules {rules}: not yet verified by a Cyprus tax professional. "
        "Sources: {src}.",
        "no_return": "This report was prepared before the boxes were added. Regenerate it, or "
        "start a new version, to see them.",
        "boxes": "Boxes",
        "rule": "Rule",
        "notice": "Prepared from the posted ledger for the owner to file on the Tax Department's "
        "portal. The platform does not file returns and is not tax advice.",
        "page": "Page {n}",
    },
    "el": {
        "title": "Αναφορά ΦΠΑ",
        "period": "Περίοδος ΦΠΑ",
        "status": "Κατάσταση",
        "version": "Έκδοση",
        "generated": "Λήψη στοιχείων",
        "watermark": "καταχώριση",
        "draft": "ΠΡΟΣΧΕΔΙΟ",
        "DRAFT": "Προσχέδιο",
        "SIGNED_OFF": "Εγκεκριμένη",
        "FILED": "Υποβλήθηκε",
        "SUPERSEDED": "Αντικαταστάθηκε",
        "self": "αυτοέγκριση (χώρος εργασίας ενός ατόμου)",
        "filed": "Υποβλήθηκε στις {on}, αριθμός {ref}",
        "due": "Ημερομηνία λήξης: {due}",
        "totals": "Σύνολα",
        "sales_base": "Πωλήσεις: φορολογητέα αξία",
        "sales_vat": "Πωλήσεις: ΦΠΑ εκροών",
        "purchase_base": "Αγορές: φορολογητέα αξία",
        "purchase_vat": "Αγορές: ΦΠΑ εισροών",
        "net": "Καθαρός ΦΠΑ",
        "PAYABLE": "πληρωτέος",
        "REFUNDABLE": "επιστρεπτέος",
        "NIL": "μηδενικός",
        "codes": "Ανά κωδικό ΦΠΑ",
        "code": "Κωδικός",
        "rate": "Συντελεστής",
        "expected": "Με τον συντελεστή",
        "unverified": "Κωδικοί ΦΠΑ που δεν έχουν ακόμη επαληθευτεί από φοροτεχνικό: {codes}.",
        "accounts": "Λογαριασμοί ΦΠΑ",
        "account": "Λογαριασμός",
        "role": "Ρόλος",
        "vat": "ΦΠΑ περιόδου",
        "settled": "Εκκαθαρίσεις",
        "checks": "Έλεγχοι",
        "none": "Καμία εξαίρεση.",
        "lines": "Γραμμές",
        "date": "Ημερομηνία",
        "entry": "Εγγραφή",
        "kind": "Είδος",
        "amount": "Ποσό",
        "description": "Περιγραφή",
        "counterparty": "Αντισυμβαλλόμενος",
        "reference": "Αναφορά",
        "return": "Δήλωση ΦΠΑ",
        "box": "Θυρίδα",
        "item": "Στοιχείο",
        "rounding": "Στρογγυλοποίηση",
        "rules": "Κανόνες θυρίδων {rules}: δεν έχουν ακόμη επαληθευτεί από φοροτεχνικό στην "
        "Κύπρο. Πηγές: {src}.",
        "no_return": "Αναφορά χωρίς θυρίδες (παλαιότερη μορφή). Ενημερώστε την ή ξεκινήστε "
        "νέα έκδοση.",
        "boxes": "Θυρίδες",
        "rule": "Κανόνας",
        "notice": "Ετοιμάστηκε από καθολικό λογιστικό, προς υποβολή από τον ιδιοκτήτη στην πύλη "
        "Τμήματος Φορολογίας. Πλατφόρμα χωρίς υποβολή δηλώσεων και χωρίς φορολογικές "
        "συμβουλές.",
        "page": "Σελίδα {n}",
    },
}


def amount(value: str, lang: Lang) -> str:
    """ "1234.5" as "1,234.50" (English) or "1.234,50" (Greek)."""
    text = f"{Decimal(value):,.2f}"
    return text.translate(str.maketrans(",.", ".,")) if lang == "el" else text


def box_amount(row: dict[str, str], lang: Lang) -> str:
    """Boxes 1-5 to the cent; Boxes 6-11B to the nearest euro."""
    if row["kind"] == "VAT":
        return amount(row["amount"], lang)
    text = f"{Decimal(row['amount']):,.0f}"
    return text.replace(",", ".") if lang == "el" else text


def return_rows(report: Any, lang: Lang) -> list[list[str]]:
    """The return as printed: box, item, amount, rounding (also used by tests)."""
    t, found = _TEXT[lang], report.snapshot.get("return")
    if not found:
        return []
    rows = [[t["box"], t["item"], t["amount"], t["rounding"]]]
    for b in found["boxes"]:
        rounding = "" if Decimal(b["rounding"]) == 0 else amount(b["rounding"], lang)
        rows.append([b["box"], b["label"], box_amount(b, lang), rounding])
    return rows


def rules_note(report: Any, lang: Lang) -> str:
    t, found = _TEXT[lang], report.snapshot.get("return")
    if not found:
        return t["no_return"]
    sources = "; ".join(s["title"] for s in found["sources"])
    return t["rules"].format(rules=found["rules"], src=sources)


def line_boxes(line: dict[str, Any]) -> str:
    return "; ".join(f"{b}: {v}" for b, v in line.get("boxes", {}).items())


def status_line(report: Any, lang: Lang) -> str:
    t = _TEXT[lang]
    line = f"{t['status']}: {t[report.status]} · {t['version']} {report.version}"
    return f"{line} · {t['self']}" if report.self_approved else line


def head_lines(report: Any, entity_name: str, lang: Lang) -> list[str]:
    t = _TEXT[lang]
    lines = [entity_name, t["title"],
             f"{t['period']}: {report.period_start.isoformat()} - {report.period_end.isoformat()}",
             status_line(report, lang),
             f"{t['generated']}: {report.generated_at.isoformat(timespec='seconds')} "
             f"({t['watermark']} #{report.watermark})"]  # fmt: skip
    if report.filed_on:
        lines.append(t["filed"].format(on=report.filed_on.isoformat(),
                                       ref=report.filing_reference))  # fmt: skip
    if report.due_date:
        lines.append(t["due"].format(due=report.due_date.isoformat()))
    lines.append(t["notice"])
    return lines


def total_rows(report: Any, lang: Lang) -> list[tuple[str, str]]:
    t, totals = _TEXT[lang], report.snapshot["totals"]
    rows = [(t[k], amount(totals[k], lang))
            for k in ("sales_base", "sales_vat", "purchase_base", "purchase_vat")]  # fmt: skip
    rows.append((f"{t['net']} ({t[totals['direction']]})", amount(totals["net"], lang)))
    return rows


def to_xlsx(report: Any, entity_name: str, lang: Lang = "en", *, generated: datetime) -> bytes:
    from openpyxl import Workbook  # noqa: PLC0415 (only exports need openpyxl)

    t, snap = _TEXT[lang], report.snapshot
    book = Workbook()
    summary = book.active
    assert summary is not None  # noqa: S101 - a new workbook always has one sheet
    summary.title = "VAT"
    for line in head_lines(report, entity_name, lang):
        summary.append([safe_text(line)])
    summary.append([f"{generated.isoformat(timespec='seconds')}"])
    summary.append([])
    summary.append([t["return"]])
    for row in return_rows(report, lang)[1:]:
        box = next(b for b in snap["return"]["boxes"] if b["box"] == row[0])
        summary.append([row[0], safe_text(row[1]), Decimal(box["amount"]),
                        Decimal(box["rounding"])])  # fmt: skip
        summary.cell(row=summary.max_row, column=3).number_format = (
            "#,##0.00" if box["kind"] == "VAT" else "#,##0"
        )
    summary.append([safe_text(rules_note(report, lang))])
    summary.append([])
    summary.append([t["totals"]])
    keys = ("sales_base", "sales_vat", "purchase_base", "purchase_vat", "net")
    for (label, _), key in zip(total_rows(report, lang), keys, strict=True):
        summary.append([label, Decimal(snap["totals"][key])])
        summary.cell(row=summary.max_row, column=2).number_format = "#,##0.00"
    if snap["unverified_codes"]:
        summary.append([t["unverified"].format(codes=", ".join(snap["unverified_codes"]))])

    codes = book.create_sheet("Codes")
    codes.append([t["code"], t["rate"], t["sales_base"], t["sales_vat"], t["expected"],
                  t["purchase_base"], t["purchase_vat"], t["expected"]])  # fmt: skip
    for c in snap["codes"]:
        codes.append([c["code"], c["rate"] or "", *[Decimal(c[k]) for k in (
            "sales_base", "sales_vat", "sales_expected_vat", "purchase_base", "purchase_vat",
            "purchase_expected_vat")]])  # fmt: skip
    accounts = book.create_sheet("Accounts")
    accounts.append([t["account"], t["role"], t["vat"], t["settled"]])
    for a in snap["accounts"]:
        accounts.append([safe_text(f"{a['code']} {a['name']}"), a["role"], Decimal(a["vat"]),
                         Decimal(a["settled"])])  # fmt: skip
    checks = book.create_sheet("Checks")
    checks.append([t["checks"]])
    for e in snap["exceptions"] or [{"kind": "", "detail": t["none"]}]:
        checks.append([e["kind"], safe_text(e["detail"])])
    lines = book.create_sheet("Lines")
    lines.append([t["date"], t["entry"], t["description"], t["account"], t["code"], t["kind"],
                  t["amount"], t["boxes"], t["rule"], t["counterparty"],
                  t["reference"]])  # fmt: skip
    for ln in snap["lines"]:
        lines.append([ln["date"], ln["entry_ref"], safe_text(ln["description"]),
                      safe_text(ln["account"]), ln["code"], ln["kind"], Decimal(ln["amount"]),
                      line_boxes(ln), safe_text(ln.get("rule", "")),
                      safe_text(ln["counterparty"]), safe_text(ln["reference"])])  # fmt: skip
    lines.auto_filter.ref = lines.dimensions
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def pdf_rows(report: Any, lang: Lang) -> list[list[str]]:
    """The by-code table as printed (also used by tests to compare with the API)."""
    t = _TEXT[lang]
    rows = [[t["code"], t["rate"], t["sales_base"], t["sales_vat"], t["purchase_base"],
             t["purchase_vat"]]]  # fmt: skip
    for c in report.snapshot["codes"]:
        rows.append([c["code"], c["rate"] or "", *[amount(c[k], lang) for k in (
            "sales_base", "sales_vat", "purchase_base", "purchase_vat")]])  # fmt: skip
    return rows


def to_pdf(report: Any, entity_name: str, lang: Lang = "en", *, generated: datetime) -> bytes:
    from reportlab.lib import colors  # noqa: PLC0415 (only exports need ReportLab)
    from reportlab.lib.pagesizes import A4  # noqa: PLC0415
    from reportlab.lib.styles import ParagraphStyle  # noqa: PLC0415
    from reportlab.lib.units import mm  # noqa: PLC0415
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table  # noqa: PLC0415

    regular, bold = pdf_fonts()
    t, snap = _TEXT[lang], report.snapshot
    body = ParagraphStyle("body", fontName=regular, fontSize=9, leading=12)
    heading = ParagraphStyle("heading", fontName=bold, fontSize=12, leading=16)
    draft = report.status not in ("SIGNED_OFF", "FILED")

    def decorate(canvas: Any, doc: Any) -> None:
        width, height = doc.pagesize
        canvas.saveState()
        canvas.setFont(regular, 7)
        canvas.drawString(
            15 * mm,
            8 * mm,
            f"{entity_name} · {t['title']} "
            f"{report.period_start.isoformat()} - {report.period_end.isoformat()}",
        )
        canvas.drawRightString(width - 15 * mm, 8 * mm, t["page"].format(n=doc.page))
        if draft:
            canvas.setFont(bold, 80)
            canvas.setFillColor(colors.HexColor("#f2c4c4"))
            canvas.translate(width / 2, height / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, t["draft"])
        canvas.restoreState()

    def table(rows: list[list[str]]) -> Table:
        found = Table(rows, repeatRows=1)
        found.setStyle([("FONT", (0, 0), (-1, -1), regular, 8),
                        ("FONT", (0, 0), (-1, 0), bold, 8),
                        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                        ("LINEBELOW", (0, 0), (-1, 0), RULE, colors.black)])  # fmt: skip
        return found

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=16 * mm, title=t["title"],
                            author=entity_name)  # fmt: skip
    head = head_lines(report, entity_name, lang)
    story: list[Any] = [Paragraph(escape(line), heading if i < 2 else body)
                        for i, line in enumerate(head)]  # fmt: skip
    story += [Spacer(1, 4 * mm), Paragraph(escape(t["return"]), heading)]
    if return_rows(report, lang):
        story.append(table(return_rows(report, lang)))
    story.append(Paragraph(escape(rules_note(report, lang)), body))
    story += [Spacer(1, 4 * mm), Paragraph(escape(t["totals"]), heading),
              table([["", ""], *[list(r) for r in total_rows(report, lang)]])]  # fmt: skip
    story += [
        Spacer(1, 4 * mm),
        Paragraph(escape(t["codes"]), heading),
        table(pdf_rows(report, lang)),
    ]
    if snap["unverified_codes"]:
        story.append(Paragraph(escape(t["unverified"].format(
            codes=", ".join(snap["unverified_codes"]))), body))  # fmt: skip
    story += [Spacer(1, 4 * mm), Paragraph(escape(t["checks"]), heading)]
    story += [Paragraph(escape(e["detail"]), body) for e in snap["exceptions"]] or [
        Paragraph(escape(t["none"]), body)]  # fmt: skip
    rows = [[t["date"], t["entry"], t["account"], t["code"], t["kind"], t["amount"], t["boxes"]]]
    rows += [[ln["date"], ln["entry_ref"], ln["account"][:36], ln["code"], ln["kind"],
              amount(ln["amount"], lang), line_boxes(ln)] for ln in snap["lines"]]  # fmt: skip
    story += [Spacer(1, 4 * mm), Paragraph(escape(t["lines"]), heading), table(rows)]
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()
