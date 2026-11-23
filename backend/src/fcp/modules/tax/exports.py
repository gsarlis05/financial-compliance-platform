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
        "REVIEWED": "Reviewed",
        "FINALISED": "Finalised",
        "steps": "Prepared {prepared}",
        "reviewed": "reviewed {at}",
        "finalised": "finalised {at}",
        "from_books": "From the books",
        "adjustment": "Adjustment",
        "adjustments": "Adjustments",
        "reason": "Reason",
        "evidence": "Evidence",
        "adj_status": "Status",
        "PROPOSED": "Proposed",
        "APPROVED": "Approved",
        "REJECTED": "Rejected",
        "evidence_filed": "Filing evidence: {evidence}",
        "party": "Customer or supplier",
        "country": "Country",
        "vat_no": "VAT number",
        "type": "Type",
        "net_value": "Net",
        "net_sale": "Net sale",
        "output_vat": "Output VAT",
        "net_purchase": "Net purchase",
        "input_vat": "Input VAT (recoverable)",
        "blocked": "Non-recoverable VAT",
        "total": "Total",
        "GOODS_SUPPLIED": "Goods supplied",
        "SERVICES_SUPPLIED": "Services supplied",
        "GOODS_ACQUIRED": "Goods acquired",
        "SERVICES_RECEIVED": "Services received",
        "EU_GOODS_ACQUISITION": "EU goods acquisition",
        "RC_EU_SERVICES": "EU services",
        "RC_NON_EU_SERVICES": "Non-EU services",
        "RC_DOMESTIC": "Domestic reverse charge",
        "LEGACY_REVERSE_CHARGE": "Reverse charge (earlier code)",
        "reconciliation": "Reconciliation",
        "opening": "Opening",
        "closing": "Closing",
        "unexplained": "Unexplained",
        "side": "Side",
        "ledger": "Ledger",
        "return_side": "Return",
        "NOT_IN_A_BOX": "VAT lines in no box",
        "ADJUSTMENTS": "Adjustments",
        "OUTPUT": "Output VAT (Boxes 1 + 2)",
        "INPUT": "Input VAT (Box 4)",
        "apart": "Payments, refunds and settlements, kept apart from Box 5: {amount}",
        "category": "Category",
        "mapping": "Tax code mapping",
        "OUTPUT_VAT": "Output VAT",
        "INPUT_VAT": "Input VAT",
        "NET_SALE": "Net sale",
        "NET_PURCHASE": "Net purchase",
        "excluded": "excluded",
        "unsupported": "not in a box",
        "schedule_sales": "Sales",
        "schedule_purchases": "Purchases",
        "schedule_eu_trade": "EU trade",
        "schedule_reverse_charge": "Reverse charge",
        "schedule_imports": "Imports",
        "customs_reference": "Customs reference",
        "customs_date": "Customs date",
        "customs_value": "Taxable value (customs)",
        "document_name": "Evidence",
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
        "REVIEWED": "Ελέγχθηκε",
        "FINALISED": "Οριστική",
        "steps": "Ετοιμάστηκε {prepared}",
        "reviewed": "ελέγχθηκε {at}",
        "finalised": "οριστικοποιήθηκε {at}",
        "from_books": "Από τα βιβλία",
        "adjustment": "Προσαρμογή",
        "adjustments": "Προσαρμογές",
        "reason": "Αιτιολογία",
        "evidence": "Τεκμήριο",
        "adj_status": "Κατάσταση",
        "PROPOSED": "Προτάθηκε",
        "APPROVED": "Εγκρίθηκε",
        "REJECTED": "Απορρίφθηκε",
        "evidence_filed": "Τεκμήριο υποβολής: {evidence}",
        "party": "Πελάτης ή προμηθευτής",
        "country": "Χώρα",
        "vat_no": "Αριθμός ΦΠΑ",
        "type": "Είδος",
        "net_value": "Καθαρή αξία",
        "net_sale": "Καθαρή πώληση",
        "output_vat": "ΦΠΑ εκροών",
        "net_purchase": "Καθαρή αγορά",
        "input_vat": "ΦΠΑ εισροών (ανακτήσιμος)",
        "blocked": "Μη ανακτήσιμος ΦΠΑ",
        "total": "Σύνολο",
        "GOODS_SUPPLIED": "Παράδοση αγαθών",
        "SERVICES_SUPPLIED": "Παροχή υπηρεσιών",
        "GOODS_ACQUIRED": "Απόκτηση αγαθών",
        "SERVICES_RECEIVED": "Λήψη υπηρεσιών",
        "EU_GOODS_ACQUISITION": "Απόκτηση αγαθών από άλλο κράτος μέλος",
        "RC_EU_SERVICES": "Υπηρεσίες από άλλο κράτος μέλος",
        "RC_NON_EU_SERVICES": "Υπηρεσίες από τρίτη χώρα",
        "RC_DOMESTIC": "Εγχώρια αντίστροφη χρέωση",
        "LEGACY_REVERSE_CHARGE": "Αντίστροφη χρέωση (παλαιότερος κωδικός)",
        "reconciliation": "Συμφωνία",
        "opening": "Έναρξη",
        "closing": "Λήξη",
        "unexplained": "Ανεξήγητο",
        "side": "Πλευρά",
        "ledger": "Καθολικό",
        "return_side": "Δήλωση",
        "NOT_IN_A_BOX": "Γραμμές ΦΠΑ εκτός θυρίδων",
        "ADJUSTMENTS": "Προσαρμογές",
        "OUTPUT": "ΦΠΑ εκροών (θυρίδες 1 + 2)",
        "INPUT": "ΦΠΑ εισροών (θυρίδα 4)",
        "apart": "Πληρωμές, επιστροφές και εκκαθαρίσεις, χωριστά από τη θυρίδα 5: {amount}",
        "category": "Κατηγορία",
        "mapping": "Αντιστοίχιση κωδικών",
        "OUTPUT_VAT": "ΦΠΑ εκροών",
        "INPUT_VAT": "ΦΠΑ εισροών",
        "NET_SALE": "Καθαρή πώληση",
        "NET_PURCHASE": "Καθαρή αγορά",
        "excluded": "εξαιρείται",
        "unsupported": "εκτός θυρίδων",
        "schedule_sales": "Πωλήσεις",
        "schedule_purchases": "Αγορές",
        "schedule_eu_trade": "Ενδοκοινοτικές συναλλαγές",
        "schedule_reverse_charge": "Αντίστροφη χρέωση",
        "schedule_imports": "Εισαγωγές",
        "customs_reference": "Αριθμός τελωνειακής διασάφησης",
        "customs_date": "Ημερομηνία τελωνείου",
        "customs_value": "Φορολογητέα αξία (τελωνείο)",
        "document_name": "Τεκμήριο",
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


def _final(report: Any) -> dict[str, Any] | None:
    from .services import final_return  # noqa: PLC0415 (exports are read after services load)

    return final_return(report)


def return_rows(report: Any, lang: Lang) -> list[list[str]]:
    """The return as printed: box, item, amount, rounding, and, once adjusted, the amount from
    the books and the adjustment (also used by tests)."""
    t, found = _TEXT[lang], _final(report)
    if not found:
        return []
    extra = found["adjusted"]
    rows = [[t["box"], t["item"], t["amount"], t["rounding"],
             *([t["from_books"], t["adjustment"]] if extra else [])]]  # fmt: skip
    for b in found["boxes"]:
        rounding = "" if Decimal(b["rounding"]) == 0 else amount(b["rounding"], lang)
        more = [box_amount({**b, "amount": b["original"]}, lang),
                "" if Decimal(b["adjustment"]) == 0 else amount(b["adjustment"], lang)]  # fmt: skip
        rows.append([b["box"], b["label"], box_amount(b, lang), rounding, *(more if extra else [])])
    return rows


def adjustment_rows(report: Any, lang: Lang) -> list[list[str]]:
    t = _TEXT[lang]
    rows = [[t["box"], t["amount"], t["reason"], t["evidence"], t["adj_status"]]]
    for a in report.adjustments.order_by("created_at"):
        rows.append([a.box, amount(str(a.amount), lang), a.reason, a.evidence, t[a.status]])
    return rows if len(rows) > 1 else []


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
    steps = [t["steps"].format(prepared=report.created_at.isoformat(timespec="minutes"))]
    if report.reviewed_at:
        steps.append(t["reviewed"].format(at=report.reviewed_at.isoformat(timespec="minutes")))
    if report.finalised_at:
        steps.append(t["finalised"].format(at=report.finalised_at.isoformat(timespec="minutes")))
    lines.append("; ".join(steps))
    if report.filed_on:
        lines.append(t["filed"].format(on=report.filed_on.isoformat(),
                                       ref=report.filing_reference))  # fmt: skip
        if report.filing_evidence:
            lines.append(t["evidence_filed"].format(evidence=report.filing_evidence))
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


SHEETS = {"sales": "Sales", "purchases": "Purchases", "eu_trade": "EU Trade",
          "reverse_charge": "Reverse Charge", "imports": "Imports"}  # fmt: skip
COLUMNS = {
    "sales": ("date", "entry", "party", "country", "vat_no", "reference", "code", "net_sale",
              "output_vat", "boxes"),
    "purchases": ("date", "entry", "party", "country", "vat_no", "reference", "code",
                  "net_purchase", "input_vat", "blocked", "boxes"),
    "eu_trade": ("date", "entry", "type", "party", "country", "vat_no", "reference", "code",
                 "net", "boxes"),
    "reverse_charge": ("date", "entry", "type", "party", "country", "vat_no", "reference", "code",
                       "net_purchase", "output_vat", "input_vat", "blocked", "boxes"),
    "imports": ("date", "entry", "customs_reference", "customs_date", "party", "code",
                "customs_value", "net_purchase", "input_vat", "blocked", "document_name"),
}  # fmt: skip
AMOUNTS = frozenset(("net_sale", "output_vat", "net_purchase", "input_vat", "blocked", "net",
                     "customs_value"))  # fmt: skip
FIELD = {"entry": "entry_ref", "party": "counterparty"}


def _schedules(report: Any) -> dict[str, Any]:
    from .services import report_schedules  # noqa: PLC0415 (exports are read after services load)

    return report_schedules(report)


def _reconciliation(report: Any) -> dict[str, Any] | None:
    from .services import report_reconciliation  # noqa: PLC0415

    return report_reconciliation(report)


def schedule_rows(report: Any, name: str, lang: Lang, *, numbers: bool = False) -> list[list[Any]]:
    """One schedule as a table: a heading row, a row per entry and VAT code, and the totals."""
    t, found = _TEXT[lang], _schedules(report)[name]
    columns = COLUMNS[name]
    rows: list[list[Any]] = [[t["net_value" if c == "net" else c] for c in columns]]

    def cell(row: dict[str, Any], column: str) -> Any:
        if column == "boxes":
            return "; ".join(f"{b}: {v}" for b, v in row["boxes"].items())
        if column == "type":
            return t.get(row["type"], row["type"])
        value = row[FIELD.get(column, column)]
        if column in AMOUNTS:
            return Decimal(value) if numbers else amount(value, lang)
        return value if numbers else str(value)

    rows += [[cell(r, c) for c in columns] for r in found["rows"]]
    if found["rows"]:
        total: list[Any] = [t["total"], *[""] * (len(columns) - 1)]
        for i, column in enumerate(columns):
            if column in AMOUNTS:
                value = found["totals"][column]
                total[i] = Decimal(value) if numbers else amount(value, lang)
        rows.append(total)
    return rows


def reconciliation_rows(report: Any, lang: Lang) -> list[list[str]]:
    t, found = _TEXT[lang], _reconciliation(report)
    if found is None:
        return []
    rows = [[t["account"], t["role"], t["opening"], t["vat"], t["settled"], t["closing"],
             t["unexplained"]]]  # fmt: skip
    keys = ("opening", "vat", "settled", "closing", "unexplained")
    rows += [[f"{a['code']} {a['name']}", a["role"], *[amount(a[k], lang) for k in keys]]
             for a in found["accounts"]]  # fmt: skip
    rows.append([t["side"], t["ledger"], t["NOT_IN_A_BOX"], t["ADJUSTMENTS"], t["return_side"],
                 "", t["unexplained"]])  # fmt: skip
    for b in found["bridges"]:
        items = {i["item"]: i["amount"] for i in b["items"]}
        rows.append([t[b["side"]], amount(b["ledger"], lang),
                     amount(items.get("NOT_IN_A_BOX", "0"), lang),
                     amount(items.get("ADJUSTMENTS", "0"), lang), amount(b["return"], lang), "",
                     amount(b["unexplained"], lang)])  # fmt: skip
    rows.append([t["apart"].format(amount=amount(found["settlements"], lang)), "", "", "", "", "",
                 ""])  # fmt: skip
    return rows


def mapping_rows(report: Any, lang: Lang) -> list[list[str]]:
    """Each VAT code of the report with the boxes each kind of its lines feeds."""
    from .boxes import LineKind, mapping  # noqa: PLC0415

    t, snap = _TEXT[lang], report.snapshot
    rules = (snap.get("return") or {}).get("rules")
    if not rules:
        return []
    categories = {ln["code"]: ln.get("category", "") for ln in snap["lines"]}
    kinds: tuple[LineKind, ...] = ("OUTPUT_VAT", "INPUT_VAT", "NET_SALE", "NET_PURCHASE")
    rows = [[t["code"], t["category"], t["rate"], *[t[k] for k in kinds]]]
    for c in snap["codes"]:
        category = categories.get(c["code"], "")
        cells = []
        for kind in kinds:
            found = mapping(category, kind, rules)
            word = t["excluded" if found.status == "EXCLUDED" else "unsupported"]
            cells.append(", ".join(found.boxes) if found.status == "MAPPED" else word)
        rows.append([c["code"], category, c["rate"] or "", *cells])
    return rows


def _sheet(book: Any, title: str, rows: list[list[Any]]) -> None:
    sheet = book.create_sheet(title)
    for row in rows:
        sheet.append([safe_text(c) if isinstance(c, str) else c for c in row])
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, Decimal):
                cell.number_format = "#,##0.00"
    if len(rows) > 1:
        sheet.auto_filter.ref = sheet.dimensions


CSV_COLUMNS = ("line_id", "entry_id", "entry_ref", "date", "account", "code", "category",
               "kind", "amount", "counterparty", "country", "vat_no", "reference", "tax_point",
               "recovery_percent", "blocked", "mapping", "rule", "rules")  # fmt: skip


def to_csv(report: Any, entity_name: str, lang: Lang = "en", *, generated: datetime) -> bytes:
    """Every line of the report with its contribution to each box (UTF-8, comma-separated,
    columns as ``CSV_COLUMNS`` then one per box; documented in the VAT guide)."""
    import csv  # noqa: PLC0415

    del entity_name, lang, generated  # the CSV is the same in every language
    from .boxes import ALL_BOXES  # noqa: PLC0415

    snap = report.snapshot
    rules = (snap.get("return") or {}).get("rules", "")
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([*CSV_COLUMNS, *[f"box_{b}" for b in ALL_BOXES]])
    for ln in snap["lines"]:
        row = {**ln, "rules": rules}
        boxes = ln.get("boxes", {})
        writer.writerow([safe_text(str(row.get(c) or "")) for c in CSV_COLUMNS]
                        + [boxes.get(b, "") for b in ALL_BOXES])  # fmt: skip
    return buffer.getvalue().encode("utf-8")


def to_xlsx(report: Any, entity_name: str, lang: Lang = "en", *, generated: datetime) -> bytes:
    from openpyxl import Workbook  # noqa: PLC0415 (only exports need openpyxl)

    t, snap = _TEXT[lang], report.snapshot
    book = Workbook()
    summary = book.active
    assert summary is not None  # noqa: S101 - a new workbook always has one sheet
    summary.title = "Summary"
    for line in head_lines(report, entity_name, lang):
        summary.append([safe_text(line)])
    summary.append([f"{generated.isoformat(timespec='seconds')}"])
    summary.append([])
    summary.append([t["return"]])
    final = _final(report)
    boxes = final["boxes"] if final else []
    adjusted = bool(final and final["adjusted"])
    if final:
        summary.append([safe_text(c) for c in return_rows(report, lang)[0]])
    for box in boxes:
        extra = [Decimal(box["original"]), Decimal(box["adjustment"])] if adjusted else []
        summary.append([box["box"], safe_text(box["label"]), Decimal(box["amount"]),
                        Decimal(box["rounding"]), *extra])  # fmt: skip
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

    for name, title in SHEETS.items():
        _sheet(book, title, schedule_rows(report, name, lang, numbers=True))
    _sheet(book, "Adjustments", adjustment_rows(report, lang)
           or [[t["box"], t["amount"], t["reason"], t["evidence"], t["adj_status"]]])  # fmt: skip
    _sheet(book, "Reconciliation", reconciliation_rows(report, lang))
    _sheet(book, "Exceptions", [[t["kind"], t["entry"], t["checks"]],
                                *[[e["kind"], e["entry"], e["detail"]]
                                  for e in snap["exceptions"]]])  # fmt: skip
    _sheet(book, "Tax Code Mapping", mapping_rows(report, lang))
    codes = book.create_sheet("Codes")
    codes.append([t["code"], t["rate"], t["sales_base"], t["sales_vat"], t["expected"],
                  t["purchase_base"], t["purchase_vat"], t["expected"]])  # fmt: skip
    for c in snap["codes"]:
        codes.append([c["code"], c["rate"] or "", *[Decimal(c[k]) for k in (
            "sales_base", "sales_vat", "sales_expected_vat", "purchase_base", "purchase_vat",
            "purchase_expected_vat")]])  # fmt: skip
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


def _pdf_schedules(report: Any, lang: Lang, table: Any, heading: Any, body: Any) -> list[Any]:
    """The schedules and the reconciliation, as PDF tables."""
    from reportlab.lib.units import mm  # noqa: PLC0415
    from reportlab.platypus import Paragraph, Spacer  # noqa: PLC0415

    t, story = _TEXT[lang], []
    for name in SHEETS:
        found = schedule_rows(report, name, lang)
        if len(found) > 1:
            story += [Spacer(1, 4 * mm), Paragraph(escape(t[f"schedule_{name}"]), heading),
                      table([[str(c)[:28] for c in r] for r in found])]  # fmt: skip
    recon = reconciliation_rows(report, lang)
    if recon:
        story += [Spacer(1, 4 * mm), Paragraph(escape(t["reconciliation"]), heading),
                  table([[c[:32] for c in r] for r in recon[:-1]]),
                  Paragraph(escape(recon[-1][0]), body)]  # fmt: skip
    return story


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
    draft = report.status not in ("FINALISED", "FILED")

    def decorate(canvas: Any, doc: Any) -> None:
        width, height = doc.pagesize
        canvas.saveState()
        canvas.setFont(regular, 7)
        canvas.drawString(
            15 * mm,
            8 * mm,
            f"{entity_name} · {t['title']} "
            f"{report.period_start.isoformat()} - {report.period_end.isoformat()} · "
            f"{t['version']} {report.version}",
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
    adjustments = adjustment_rows(report, lang)
    if adjustments:
        story += [Spacer(1, 4 * mm), Paragraph(escape(t["adjustments"]), heading),
                  table([[c[:60] for c in r] for r in adjustments])]  # fmt: skip
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
    story += _pdf_schedules(report, lang, table, heading, body)
    rows = [[t["date"], t["entry"], t["account"], t["code"], t["kind"], t["amount"], t["boxes"]]]
    rows += [[ln["date"], ln["entry_ref"], ln["account"][:36], ln["code"], ln["kind"],
              amount(ln["amount"], lang), line_boxes(ln)] for ln in snap["lines"]]  # fmt: skip
    story += [Spacer(1, 4 * mm), Paragraph(escape(t["lines"]), heading), table(rows)]
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()
