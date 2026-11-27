"""Public interface of the ``tax`` module: VAT periods and VAT period reports (V1-2; four steps,
adjustments and differences V1-2d).

This is the only part of ``fcp.modules.tax`` that other modules may import.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from ninja import Field, Query, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.core.errors import ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.taxrules.api import Kind, add_correction, all_for, latest_by_target
from fcp.modules.tenancy.api import get_entity, workspace_ctx

from . import exports, services
from .boxes import ALL_BOXES, mapping, ruleset
from .boxes import key as box_key
from .models import VatAdjustment, VatImport, VatPeriodScheme, VatReport

__all__ = ["router"]

router = Router(tags=["VAT"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"


class SchemeIn(Schema):
    months: int = Field(description="1, 2, 3, 4, 6 or 12")
    effective_from: date = Field(description="The first day of the first period under it")
    note: str = Field(default="", max_length=500, description="e.g. the Tax Department's letter")


class SchemeOut(Schema):
    id: UUID
    months: int
    effective_from: date
    note: str
    created_at: datetime


class ReportOut(Schema):
    id: UUID
    period_start: date
    period_end: date
    version: int
    supersedes_id: UUID | None
    status: str
    snapshot_hash: str
    watermark: int
    generated_at: datetime
    created_by_id: UUID
    created_at: datetime
    due_date: date | None
    reviewed_by_id: UUID | None
    reviewed_at: datetime | None
    review_note: str = Field(description="Why it was last sent back to draft")
    finalised_by_id: UUID | None
    finalised_at: datetime | None
    self_approved: bool = Field(
        description="Reviewed or finalised by its preparer (one-person workspace)"
    )
    filed_on: date | None
    filing_reference: str
    filing_evidence: str
    settlement_entry_id: UUID | None


class AdjustmentOut(Schema):
    id: UUID
    box: str
    amount: Decimal
    reason: str
    evidence: str
    status: str
    created_by_id: UUID
    created_at: datetime
    decided_by_id: UUID | None
    decided_at: datetime | None
    decision_note: str
    self_approved: bool


class ReportDetailOut(ReportOut):
    snapshot: dict[str, Any] = Field(description="Every figure, check and line, frozen")
    final_return: dict[str, Any] | None = Field(
        description="The return after approved adjustments: original, adjustment, final per box"
    )
    adjustments: list[AdjustmentOut]
    blockers: list[str] = Field(description="Why it cannot take its next step yet")
    differences: dict[str, Any] | None = Field(
        description="Reviewed or later: lines posted or reversed in the period since it was "
        "prepared, and the change to each box"
    )
    previous: dict[str, Any] | None = Field(
        description="A new version: the version it corrects and the change to each box"
    )
    schedules: dict[str, Any] = Field(
        description="Sales, purchases, EU trade, reverse charge, imports, adjustments, exceptions"
    )
    vies: dict[str, Any] = Field(
        description="EU supplies against the VIES statements recorded, and Boxes 8A and 8B"
    )
    reconciliation: dict[str, Any] | None = Field(
        description="The VAT accounts from opening to closing, and the return bridged to the ledger"
    )


class VatPeriodOut(Schema):
    start: date
    end: date
    months: int
    ended: bool
    report: ReportOut | None


class GenerateIn(Schema):
    period_start: date


class DueIn(Schema):
    due_date: date | None = None


class FiledIn(Schema):
    filed_on: date
    reference: str = Field(min_length=1, max_length=100)
    evidence: str = Field(min_length=1, max_length=500,
                          description="Where the portal's acknowledgement is kept")  # fmt: skip


class VatNoteIn(Schema):
    note: str = Field(min_length=1, max_length=500)


class AdjustmentIn(Schema):
    box: str = Field(description="1, 2, 4, 6, 7, 8A, 8B, 9, 10, 11A or 11B")
    amount: Decimal = Field(max_digits=19, decimal_places=2, description="Signed, in euros")
    reason: str = Field(min_length=1, max_length=500)
    evidence: str = Field(min_length=1, max_length=500)


class VatDecisionIn(Schema):
    note: str = Field(default="", max_length=500)


class SettlementOut(Schema):
    entry_id: UUID


class VatExportQuery(Schema):
    format: Literal["xlsx", "pdf", "csv"]
    lang: Literal["en", "el"] = "en"


def _detail(ctx: Any, r: VatReport) -> ReportDetailOut:
    open_ = r.status in (VatReport.Status.DRAFT, VatReport.Status.REVIEWED)
    later = r.status in (VatReport.Status.REVIEWED, VatReport.Status.FINALISED,
                         VatReport.Status.FILED)  # fmt: skip
    base = ReportOut.from_orm(r).model_dump()
    return ReportDetailOut.model_validate({
        **base, "snapshot": r.snapshot, "final_return": services.final_return(r),
        "adjustments": [AdjustmentOut.from_orm(a) for a in r.adjustments.order_by("created_at")],
        "blockers": services.blockers(ctx, r) if open_ else [],
        "differences": services.differences(ctx, r) if later else None,
        "previous": services.previous_version(r),
        "schedules": services.report_schedules(r),
        "reconciliation": services.report_reconciliation(r),
        "vies": services.report_vies(r),
    })  # fmt: skip


@router.get(f"{BASE}/vat-period-schemes", response=list[SchemeOut])
@requires("tax.vat.read")
def list_schemes(request: HttpRequest, slug: str, entity_id: UUID) -> list[VatPeriodScheme]:
    """How the entity's VAT periods run, oldest first."""
    return services.schemes(workspace_ctx(request, slug, entity_id), entity_id)


@router.post(f"{BASE}/vat-period-schemes", response={201: SchemeOut})
@requires("tax.vat.sign_off")
def add_scheme(request: HttpRequest, slug: str, entity_id: UUID,
               payload: SchemeIn) -> Status[VatPeriodScheme]:  # fmt: skip
    """Set the VAT periods, or change them from the start of a later period."""
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(201, services.add_scheme(ctx, entity_id, months=payload.months,
                                           effective_from=payload.effective_from,
                                           note=payload.note))  # fmt: skip


@router.get(f"{BASE}/vat-periods", response=list[VatPeriodOut])
@requires("tax.vat.read")
def list_periods(request: HttpRequest, slug: str, entity_id: UUID) -> list[dict[str, Any]]:
    """Every VAT period up to the current one, newest first, with its latest report."""
    return services.period_list(workspace_ctx(request, slug, entity_id), entity_id)


@router.post(f"{BASE}/vat-reports", response={201: ReportDetailOut})
@requires("tax.vat.prepare")
def generate(request: HttpRequest, slug: str, entity_id: UUID,
             payload: GenerateIn) -> Status[ReportDetailOut]:  # fmt: skip
    """Compute a period's VAT report from the posted ledger and freeze it as a draft."""
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(201, _detail(ctx, services.generate(ctx, entity_id, payload.period_start)))


@router.get(f"{BASE}/vat-reports/{{uuid:report_id}}", response=ReportDetailOut)
@requires("tax.vat.read")
def get_report(request: HttpRequest, slug: str, entity_id: UUID,
               report_id: UUID) -> ReportDetailOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return _detail(ctx, services.get(ctx, entity_id, report_id))


@router.post(f"{BASE}/vat-reports/{{uuid:report_id}}/regenerate", response=ReportDetailOut)
@requires("tax.vat.prepare")
def regenerate(request: HttpRequest, slug: str, entity_id: UUID,
               report_id: UUID) -> ReportDetailOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return _detail(ctx, services.regenerate(ctx, entity_id, report_id))


@router.put(f"{BASE}/vat-reports/{{uuid:report_id}}/due-date", response=ReportDetailOut)
@requires("tax.vat.prepare")
def set_due_date(request: HttpRequest, slug: str, entity_id: UUID, report_id: UUID,
                 payload: DueIn) -> ReportDetailOut:  # fmt: skip
    """The date the return and any payment are due, as you know it (not computed)."""
    ctx = workspace_ctx(request, slug, entity_id)
    return _detail(ctx, services.set_due_date(ctx, entity_id, report_id, payload.due_date))


@router.post(f"{BASE}/vat-reports/{{uuid:report_id}}/review", response=ReportDetailOut)
@requires("tax.vat.sign_off")
def review(request: HttpRequest, slug: str, entity_id: UUID,
           report_id: UUID) -> ReportDetailOut:  # fmt: skip
    """Review a draft and freeze its figures (never your own, except in a one-person
    workspace)."""
    ctx = workspace_ctx(request, slug, entity_id)
    return _detail(ctx, services.review(ctx, entity_id, report_id))


@router.post(f"{BASE}/vat-reports/{{uuid:report_id}}/reopen", response=ReportDetailOut)
@requires("tax.vat.sign_off")
def reopen(request: HttpRequest, slug: str, entity_id: UUID, report_id: UUID,
           payload: VatNoteIn) -> ReportDetailOut:  # fmt: skip
    """Send a reviewed report back to draft, saying why."""
    ctx = workspace_ctx(request, slug, entity_id)
    return _detail(ctx, services.reopen(ctx, entity_id, report_id, payload.note))


@router.post(f"{BASE}/vat-reports/{{uuid:report_id}}/finalise", response=ReportDetailOut)
@requires("tax.vat.sign_off")
def finalise(request: HttpRequest, slug: str, entity_id: UUID,
             report_id: UUID) -> ReportDetailOut:  # fmt: skip
    """Finalise a reviewed report for filing; records the inclusion of each of its lines."""
    ctx = workspace_ctx(request, slug, entity_id)
    return _detail(ctx, services.finalise(ctx, entity_id, report_id))


@router.post(f"{BASE}/vat-reports/{{uuid:report_id}}/adjustments",
             response={201: AdjustmentOut})  # fmt: skip
@requires("tax.vat.prepare")
def propose_adjustment(request: HttpRequest, slug: str, entity_id: UUID, report_id: UUID,
                       payload: AdjustmentIn) -> Status[VatAdjustment]:  # fmt: skip
    """Propose a manual adjustment of one box of a draft, with a reason and evidence."""
    ctx = workspace_ctx(request, slug, entity_id)
    data = services.AdjustmentInput(box=payload.box, amount=payload.amount,
                                    reason=payload.reason, evidence=payload.evidence)  # fmt: skip
    return Status(201, services.propose_adjustment(ctx, entity_id, report_id, data))


@router.post(f"{BASE}/vat-reports/{{uuid:report_id}}/adjustments/{{uuid:adjustment_id}}/approve",
             response=AdjustmentOut)  # fmt: skip
@requires("tax.vat.sign_off")
def approve_adjustment(request: HttpRequest, slug: str, entity_id: UUID, report_id: UUID,
                       adjustment_id: UUID, payload: VatDecisionIn) -> VatAdjustment:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return services.decide_adjustment(ctx, entity_id, report_id, adjustment_id, approve=True,
                                      note=payload.note)  # fmt: skip


@router.post(f"{BASE}/vat-reports/{{uuid:report_id}}/adjustments/{{uuid:adjustment_id}}/reject",
             response=AdjustmentOut)  # fmt: skip
@requires("tax.vat.prepare")
def reject_adjustment(request: HttpRequest, slug: str, entity_id: UUID, report_id: UUID,
                      adjustment_id: UUID, payload: VatDecisionIn) -> VatAdjustment:  # fmt: skip
    """Reject a proposed adjustment (``tax.vat.sign_off``), or withdraw your own."""
    ctx = workspace_ctx(request, slug, entity_id)
    return services.decide_adjustment(ctx, entity_id, report_id, adjustment_id, approve=False,
                                      note=payload.note)  # fmt: skip


@router.post(f"{BASE}/vat-reports/{{uuid:report_id}}/filed", response=ReportDetailOut)
@requires("tax.vat.sign_off")
def mark_filed(request: HttpRequest, slug: str, entity_id: UUID, report_id: UUID,
               payload: FiledIn) -> ReportDetailOut:  # fmt: skip
    """Record that you filed the return on the Tax Department's portal. Nothing is sent."""
    ctx = workspace_ctx(request, slug, entity_id)
    found = services.mark_filed(ctx, entity_id, report_id, filed_on=payload.filed_on,
                                reference=payload.reference,
                                evidence=payload.evidence)  # fmt: skip
    return _detail(ctx, found)


@router.post(f"{BASE}/vat-reports/{{uuid:report_id}}/new-version", response={201: ReportDetailOut})
@requires("tax.vat.prepare")
def new_version(request: HttpRequest, slug: str, entity_id: UUID,
                report_id: UUID) -> Status[ReportDetailOut]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(201, _detail(ctx, services.new_version(ctx, entity_id, report_id)))


@router.post(f"{BASE}/vat-reports/{{uuid:report_id}}/settlement", response={201: SettlementOut})
@requires("tax.vat.prepare")
def prepare_settlement(request: HttpRequest, slug: str, entity_id: UUID,
                       report_id: UUID) -> Status[SettlementOut]:  # fmt: skip
    """A draft entry moving the period's input VAT into the output VAT account."""
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(201, SettlementOut(entry_id=services.prepare_settlement(ctx, entity_id,
                                                                          report_id)))  # fmt: skip


class VatImportIn(Schema):
    entry_id: UUID = Field(description="The posted entry that claims the import VAT")
    customs_reference: str = Field(min_length=1, max_length=50)
    customs_date: date
    customs_value: Decimal = Field(gt=0, max_digits=19, decimal_places=2)
    import_vat: Decimal = Field(gt=0, max_digits=19, decimal_places=2)
    document_id: UUID = Field(description="The customs declaration, attached to the entry")


class VatImportOut(Schema):
    id: UUID
    entry_id: UUID
    customs_reference: str
    customs_date: date
    customs_value: Decimal
    import_vat: Decimal
    document_id: UUID
    document_name: str
    created_at: datetime
    voided_at: datetime | None
    void_reason: str


class VatImportsQuery(Schema):
    date_from: date
    date_to: date


class VoidIn(Schema):
    reason: str = Field(min_length=1, max_length=500)


@router.get(f"{BASE}/vat-imports", response=dict[str, Any])
@requires("tax.vat.read")
def list_imports(request: HttpRequest, slug: str, entity_id: UUID,
                 query: Query[VatImportsQuery]) -> dict[str, Any]:  # fmt: skip
    """Import records of the entries in the dates, and the import VAT claims without one."""
    ctx = workspace_ctx(request, slug, entity_id)
    return services.imports(ctx, entity_id, date_from=query.date_from, date_to=query.date_to)


@router.post(f"{BASE}/vat-imports", response={201: VatImportOut})
@requires("tax.vat.prepare")
def record_import(request: HttpRequest, slug: str, entity_id: UUID,
                  payload: VatImportIn) -> Status[VatImport]:  # fmt: skip
    """Record the customs declaration behind an entry's import VAT; a reference is recorded once."""
    ctx = workspace_ctx(request, slug, entity_id)
    data = services.ImportInput(**payload.dict())
    return Status(201, services.record_import(ctx, entity_id, data))


@router.post(f"{BASE}/vat-imports/{{uuid:import_id}}/void", response=VatImportOut)
@requires("tax.vat.prepare")
def void_import(request: HttpRequest, slug: str, entity_id: UUID, import_id: UUID,
                payload: VoidIn) -> VatImport:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return services.void_import(ctx, entity_id, import_id, payload.reason)


class ViesLineIn(Schema):
    country: str = Field(pattern=r"^[A-Za-z]{2}$")
    vat_no: str = Field(min_length=1, max_length=30)
    goods: Decimal = Field(default=Decimal(0), max_digits=19, decimal_places=2)
    services: Decimal = Field(default=Decimal(0), max_digits=19, decimal_places=2)
    triangular: Decimal = Field(default=Decimal(0), max_digits=19, decimal_places=2)


class ViesIn(Schema):
    month: date = Field(description="The first day of the month it reports")
    kind: Literal["ORIGINAL", "CORRECTION"] = "ORIGINAL"
    filed_on: date
    reference: str = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=500)
    lines: list[ViesLineIn] = Field(min_length=1, max_length=500)


@router.get(f"{BASE}/vat-vies", response=list[dict[str, Any]])
@requires("tax.vat.read")
def list_vies(request: HttpRequest, slug: str, entity_id: UUID,
              query: Query[VatImportsQuery]) -> list[dict[str, Any]]:  # fmt: skip
    """The VIES statements recorded for the months in the dates."""
    ctx = workspace_ctx(request, slug, entity_id)
    return services.vies_statements(ctx, entity_id, date_from=query.date_from,
                                    date_to=query.date_to)  # fmt: skip


@router.post(f"{BASE}/vat-vies", response={201: dict[str, Any]})
@requires("tax.vat.prepare")
def record_vies(request: HttpRequest, slug: str, entity_id: UUID,
                payload: ViesIn) -> Status[dict[str, Any]]:  # fmt: skip
    """Record a VIES statement as you filed it. Nothing is sent to VIES."""
    ctx = workspace_ctx(request, slug, entity_id)
    data = services.ViesInput(
        month=payload.month, kind=payload.kind, filed_on=payload.filed_on,
        reference=payload.reference, note=payload.note,
        lines=[services.ViesLineInput(**ln.dict()) for ln in payload.lines],
    )  # fmt: skip
    return Status(201, services.vies_out(services.record_vies(ctx, entity_id, data)))


@router.post(f"{BASE}/vat-vies/{{uuid:statement_id}}/void", response=dict[str, Any])
@requires("tax.vat.prepare")
def void_vies(request: HttpRequest, slug: str, entity_id: UUID, statement_id: UUID,
              payload: VoidIn) -> dict[str, Any]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return services.vies_out(services.void_vies(ctx, entity_id, statement_id, payload.reason))


CONTENT_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
    "csv": "text/csv; charset=utf-8",
}


@router.get(f"{BASE}/vat-reports/{{uuid:report_id}}/export")
@requires("reports.export")
def export_report(request: HttpRequest, slug: str, entity_id: UUID, report_id: UUID,
                  query: Query[VatExportQuery]) -> HttpResponse:  # fmt: skip
    """The report as Excel, PDF or CSV (every line with its box contributions), from its frozen
    snapshot; DRAFT until finalised. Audited."""
    ctx = workspace_ctx(request, slug, entity_id)
    r = services.get(ctx, entity_id, report_id)
    entity = get_entity(ctx, entity_id, "tax.vat.read")
    write = {"xlsx": exports.to_xlsx, "pdf": exports.to_pdf, "csv": exports.to_csv}[query.format]
    content = write(r, entity.legal_name, query.lang, generated=timezone.now())
    draft = "" if r.status in ("FINALISED", "FILED") else "-draft"
    filename = f"vat-report-{r.period_start:%Y-%m}-{r.period_end:%Y-%m}-v{r.version}{draft}"
    filename += f".{query.format}"
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, action="reports.exported",
          subject_type="vat_report", subject_id=r.id, entity_id=entity_id,
          changes={"format": query.format, "filename": filename, "status": r.status,
                   "snapshot_hash": r.snapshot_hash})  # fmt: skip
    response = HttpResponse(content, content_type=CONTENT_TYPES[query.format])
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# --- box rule corrections (brief 27, T-2) ---------------------------------------------------------


LINE_KINDS = ("OUTPUT_VAT", "INPUT_VAT", "NET_SALE", "NET_PURCHASE")
FORMULA_BOXES = ("3", "5")  # worked out from other boxes, never mapped to


class BoxRuleCorrectionIn(Schema):
    effective_from: date = Field(description="Applies to VAT returns whose period starts then "
                                             "or later")  # fmt: skip
    category: str
    line: Literal["OUTPUT_VAT", "INPUT_VAT", "NET_SALE", "NET_PURCHASE"]
    status: Literal["MAPPED", "EXCLUDED"]
    boxes: list[str] = Field(default_factory=list, max_length=6)
    source: str = Field(min_length=1, max_length=500)
    note: str = Field(default="", max_length=1000)


class BoxRuleOut(Schema):
    category: str
    line: str
    status: str
    boxes: list[str]
    reason: str
    corrected_from: date | None


def _categories() -> list[str]:
    rules = ruleset(services.BOX_RULES["CY"])
    return sorted({r["category"] for part in ("rules", "excluded", "unsupported")
                   for r in rules[part]})  # fmt: skip


@router.get(f"{BASE}/vat-box-rules", response=list[BoxRuleOut])
@requires("tax.vat.read")
def list_box_rules(
    request: HttpRequest, slug: str, entity_id: UUID, on: date | None = None
) -> list[BoxRuleOut]:
    """Every category and line kind with the boxes it goes to for a return starting on ``on``
    (today by default), the entity's corrections included."""
    workspace_ctx(request, slug, entity_id)
    day = on or timezone.localdate()
    found = latest_by_target(all_for(entity_id, Kind.VAT_BOX_RULE), day)
    fixes = {t: c.as_ref() for t, c in found.items()}
    out = []
    for category in _categories():
        for line in LINE_KINDS:
            m = mapping(category, line, services.BOX_RULES["CY"], fixes)  # type: ignore[arg-type]
            fix = found.get(box_key(category, line))
            out.append(BoxRuleOut(category=category, line=line, status=m.status,
                                  boxes=list(m.boxes), reason=m.reason,
                                  corrected_from=fix.effective_from if fix else None))  # fmt: skip
    return out


@router.post(f"{BASE}/vat-box-rules/corrections", response={201: dict[str, Any]})
@requires("tax.rules.correct")
def correct_box_rule(
    request: HttpRequest, slug: str, entity_id: UUID, payload: BoxRuleCorrectionIn
) -> Status[dict[str, Any]]:
    """Correct which boxes a category and line kind go to, for VAT returns whose period starts on
    or after the date. Earlier returns keep the rules they used."""
    ctx = workspace_ctx(request, slug, entity_id)
    p = payload
    if p.category not in _categories():
        raise ValidationFailedError("Choose one of the VAT categories.",
                                    field_errors={"category": ["unknown"]})  # fmt: skip
    boxes = list(dict.fromkeys(b.strip().upper() for b in p.boxes))
    bad = [b for b in boxes if b not in ALL_BOXES or b in FORMULA_BOXES]
    if bad:
        raise ValidationFailedError(
            f"Not boxes a line can go to: {', '.join(bad)} (Boxes 3 and 5 are worked out).",
            field_errors={"boxes": ["invalid"]},
        )
    if (p.status == "MAPPED") != bool(boxes):
        raise ValidationFailedError(
            "A mapped rule needs at least one box; an excluded one has none.",
            field_errors={"boxes": ["required" if p.status == "MAPPED" else "not allowed"]},
        )
    found = add_correction(ctx, entity_id, kind=Kind.VAT_BOX_RULE,
                           target=box_key(p.category, p.line), effective_from=p.effective_from,
                           values={"status": p.status, "boxes": boxes}, source=p.source,
                           note=p.note)  # fmt: skip
    return Status(201, found.as_ref())
