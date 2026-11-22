"""Public interface of the ``tax`` module: VAT periods and VAT period reports (V1-2).

This is the only part of ``fcp.modules.tax`` that other modules may import.
"""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from ninja import Field, Query, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.modules.audit_log.api import record as audit
from fcp.modules.tenancy.api import get_entity, workspace_ctx

from . import exports, services
from .models import VatPeriodScheme, VatReport

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
    due_date: date | None
    signed_off_by_id: UUID | None
    signed_off_at: datetime | None
    self_approved: bool = Field(description="Signed off by its preparer (one-person workspace)")
    filed_on: date | None
    filing_reference: str
    settlement_entry_id: UUID | None


class ReportDetailOut(ReportOut):
    snapshot: dict[str, Any] = Field(description="Every figure, check and line, frozen")
    blockers: list[str] = Field(description="Draft: why it cannot be signed off yet")


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


class SettlementOut(Schema):
    entry_id: UUID


class VatExportQuery(Schema):
    format: Literal["xlsx", "pdf"]
    lang: Literal["en", "el"] = "en"


def _detail(ctx: Any, r: VatReport) -> ReportDetailOut:
    blockers = services.blockers(ctx, r) if r.status == VatReport.Status.DRAFT else []
    base = ReportOut.from_orm(r).model_dump()
    return ReportDetailOut.model_validate({**base, "snapshot": r.snapshot, "blockers": blockers})


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


@router.post(f"{BASE}/vat-reports/{{uuid:report_id}}/sign-off", response=ReportDetailOut)
@requires("tax.vat.sign_off")
def sign_off(request: HttpRequest, slug: str, entity_id: UUID,
             report_id: UUID) -> ReportDetailOut:  # fmt: skip
    """Freeze the report for filing (never your own, except in a one-person workspace)."""
    ctx = workspace_ctx(request, slug, entity_id)
    return _detail(ctx, services.sign_off(ctx, entity_id, report_id))


@router.post(f"{BASE}/vat-reports/{{uuid:report_id}}/filed", response=ReportDetailOut)
@requires("tax.vat.sign_off")
def mark_filed(request: HttpRequest, slug: str, entity_id: UUID, report_id: UUID,
               payload: FiledIn) -> ReportDetailOut:  # fmt: skip
    """Record that you filed the return on the Tax Department's portal. Nothing is sent."""
    ctx = workspace_ctx(request, slug, entity_id)
    found = services.mark_filed(ctx, entity_id, report_id, filed_on=payload.filed_on,
                                reference=payload.reference)  # fmt: skip
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


CONTENT_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


@router.get(f"{BASE}/vat-reports/{{uuid:report_id}}/export")
@requires("reports.export")
def export_report(request: HttpRequest, slug: str, entity_id: UUID, report_id: UUID,
                  query: Query[VatExportQuery]) -> HttpResponse:  # fmt: skip
    """The report as Excel or PDF, from its frozen snapshot; DRAFT until signed off. Audited."""
    ctx = workspace_ctx(request, slug, entity_id)
    r = services.get(ctx, entity_id, report_id)
    entity = get_entity(ctx, entity_id, "tax.vat.read")
    write = exports.to_xlsx if query.format == "xlsx" else exports.to_pdf
    content = write(r, entity.legal_name, query.lang, generated=timezone.now())
    draft = "" if r.status in ("SIGNED_OFF", "FILED") else "-draft"
    filename = f"vat-report-{r.period_start:%Y-%m}-{r.period_end:%Y-%m}-v{r.version}{draft}"
    filename += f".{query.format}"
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, action="reports.exported",
          subject_type="vat_report", subject_id=r.id, entity_id=entity_id,
          changes={"format": query.format, "filename": filename, "status": r.status,
                   "snapshot_hash": r.snapshot_hash})  # fmt: skip
    response = HttpResponse(content, content_type=CONTENT_TYPES[query.format])
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
