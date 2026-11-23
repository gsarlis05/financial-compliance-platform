"""VAT periods and VAT period reports (V1-2, #208; ADR-0056).

- **See**: ``tax.vat.read``. **Prepare** (generate, regenerate, set the due date, start a new
  version, prepare the settlement entry): ``tax.vat.prepare``. **Sign off** and **record the
  filing**, and **choose the VAT periods**: ``tax.vat.sign_off``.
- A report is computed from the posted ledger under the preparer's permissions and frozen. A draft
  can be regenerated; a signed-off report never changes.
- **Signing off** is refused before the period has ended and while the period's figures have
  changed since the report was generated. The person who signs off is not the preparer, except in
  a one-person workspace, where it is recorded as self-approved.
- **Filed** records that the owner filed the return on the Tax Department's portal, with its
  reference. The platform never files anything.
- A correction is a **new version**; when it is signed off, the earlier version is superseded.
Every change is audited.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from fcp.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from fcp.modules.audit_log.api import record as audit
from fcp.modules.ledger.api import (
    EntryInput,
    LineInput,
    account_list,
    create_system_draft,
    posting_watermark,
    vat_lines,
)
from fcp.modules.tenancy.api import WorkspaceContext, get_entity, self_approval_allowed

from . import periods as P
from .models import VatPeriodScheme, VatReport
from .report import Line, compute, digest, figures

READ, PREPARE, SIGN_OFF = "tax.vat.read", "tax.vat.prepare", "tax.vat.sign_off"
Status = VatReport.Status


class NotSignableError(ConflictError):
    code = "tax.vat.not_signable"


def _invalid(field: str, message: str) -> ValidationFailedError:
    return ValidationFailedError(message, field_errors={field: [message]})


def _audit(ctx: WorkspaceContext, action: str, subject: str, subject_id: UUID, entity: UUID,
           **changes: object) -> None:  # fmt: skip
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, action=f"tax.vat.{action}",
          subject_type=subject, subject_id=subject_id, entity_id=entity,
          changes=changes)  # fmt: skip


# --- VAT periods ---------------------------------------------------------------------------------


def _schemes(entity_id: UUID) -> list[P.Scheme]:
    rows = VatPeriodScheme.objects.filter(legal_entity_id=entity_id).order_by("effective_from")
    return [P.Scheme(r.months, r.effective_from) for r in rows]


def schemes(ctx: WorkspaceContext, entity_id: UUID) -> list[VatPeriodScheme]:
    entity = get_entity(ctx, entity_id, READ)
    return list(VatPeriodScheme.objects.filter(legal_entity=entity).order_by("effective_from"))


@transaction.atomic
def add_scheme(ctx: WorkspaceContext, entity_id: UUID, *, months: int, effective_from: date,
               note: str = "") -> VatPeriodScheme:  # fmt: skip
    entity = get_entity(ctx, entity_id, SIGN_OFF)
    existing = list(VatPeriodScheme.objects.select_for_update().filter(legal_entity=entity))
    problem = P.scheme_problem([P.Scheme(s.months, s.effective_from) for s in existing],
                               P.Scheme(months, effective_from))  # fmt: skip
    if problem:
        raise _invalid("effective_from" if "start" in problem or "effect" in problem
                       else "months", problem)  # fmt: skip
    settled = VatReport.objects.filter(
        legal_entity=entity, period_end__gte=effective_from,
        status__in=[Status.SIGNED_OFF, Status.FILED],
    ).exists()  # fmt: skip
    if settled:
        raise _invalid("effective_from", "A report signed off for a period on or after this date "
                       "would no longer match its period.")  # fmt: skip
    made = VatPeriodScheme.objects.create(tenant=ctx.tenant, legal_entity=entity, months=months,
                                          effective_from=effective_from, note=note.strip()[:500],
                                          created_by=ctx.user)  # fmt: skip
    _audit(ctx, "periods_set", "vat_period_scheme", made.id, entity.id, months=months,
           effective_from=effective_from.isoformat(), note=made.note)  # fmt: skip
    return made


def period_list(ctx: WorkspaceContext, entity_id: UUID, today: date | None = None
                ) -> list[dict[str, Any]]:  # fmt: skip
    """Every VAT period from the first scheme to the current one, newest first, with its latest
    report (if any)."""
    entity = get_entity(ctx, entity_id, READ)
    found = _schemes(entity.id)
    if not found:
        return []
    today = today or timezone.localdate()
    reports: dict[date, VatReport] = {}
    for r in VatReport.objects.filter(legal_entity=entity).order_by("period_start", "version"):
        reports[r.period_start] = r  # the latest version wins
    rows = []
    for p in P.periods(found, found[0].effective_from, today):
        latest = reports.get(p.start)
        rows.append({"start": p.start, "end": p.end, "months": p.months,
                     "ended": p.end < today, "report": latest})  # fmt: skip
    return rows[::-1]


# --- reports -------------------------------------------------------------------------------------


# The return's box rules for each jurisdiction (versioned data, ``boxes``).
BOX_RULES = {"CY": "CY-VAT-BOXES@1"}


def _take(
    ctx: WorkspaceContext, entity_id: UUID, start: date, end: date, jurisdiction: str = "CY"
) -> dict[str, Any]:
    rules = BOX_RULES.get(jurisdiction)
    if rules is None:
        raise _invalid("period_start", "VAT returns can be prepared for Cyprus entities only.")
    lines = [
        Line(str(v.line_id), str(v.entry_id), v.entry_ref, v.accounting_date.isoformat(),
             v.description, v.account_code, v.account_name, v.account_type, v.vat_role,
             v.vat_code, v.treatment, v.rate, v.verified, v.net_debit, v.counterparty,
             v.reference, category=v.category,
             tax_point=v.tax_point.isoformat() if v.tax_point else None,
             recovery_percent=v.vat_recovery_percent, blocked=v.vat_blocked,
             country=v.counterparty_country, vat_no=v.counterparty_vat_no)
        for v in vat_lines(ctx, entity_id, date_from=start, date_to=end)
    ]  # fmt: skip
    return compute(lines, start.isoformat(), end.isoformat(), rules)


def _get(ctx: WorkspaceContext, entity_id: UUID, report_id: UUID, permission: str,
         lock: bool = False) -> VatReport:  # fmt: skip
    entity = get_entity(ctx, entity_id, permission)
    rows = VatReport.objects.select_for_update() if lock else VatReport.objects
    found = rows.filter(legal_entity=entity, id=report_id).first()
    if found is None:
        raise NotFoundError("VAT report not found.")
    return found


def get(ctx: WorkspaceContext, entity_id: UUID, report_id: UUID) -> VatReport:
    return _get(ctx, entity_id, report_id, READ)


def _period(entity_id: UUID, start: date) -> P.Period:
    found = P.period_of(_schemes(entity_id), start)
    if found is None or found.start != start:
        raise _invalid("period_start", "Choose the first day of one of the entity's VAT periods.")
    return found


def _snapshot(ctx: WorkspaceContext, report: VatReport, jurisdiction: str) -> None:
    taken = _take(ctx, report.legal_entity_id, report.period_start, report.period_end,
                  jurisdiction)  # fmt: skip
    report.snapshot = taken
    report.snapshot_hash = digest(figures(taken))
    report.watermark = posting_watermark(ctx, report.legal_entity_id)
    report.generated_at = timezone.now()


@transaction.atomic
def generate(ctx: WorkspaceContext, entity_id: UUID, period_start: date) -> VatReport:
    entity = get_entity(ctx, entity_id, PREPARE)
    period = _period(entity.id, period_start)
    existing = VatReport.objects.select_for_update().filter(
        legal_entity=entity, period_start=period.start
    )
    if existing.exists():
        raise ConflictError("This period already has a report. Open it, regenerate the draft or "
                            "start a new version.")  # fmt: skip
    report = VatReport(tenant=ctx.tenant, legal_entity=entity, period_start=period.start,
                       period_end=period.end, created_by=ctx.user)  # fmt: skip
    _snapshot(ctx, report, entity.jurisdiction)
    report.save()
    _audit(ctx, "report_generated", "vat_report", report.id, entity.id, version=1,
           period=f"{report.period_start}/{report.period_end}",
           snapshot_hash=report.snapshot_hash)  # fmt: skip
    return report


@transaction.atomic
def regenerate(ctx: WorkspaceContext, entity_id: UUID, report_id: UUID) -> VatReport:
    report = _get(ctx, entity_id, report_id, PREPARE, lock=True)
    if report.status != Status.DRAFT:
        raise ConflictError("Only a draft can be regenerated. Start a new version instead.")
    _snapshot(ctx, report, get_entity(ctx, entity_id).jurisdiction)
    report.save()
    _audit(ctx, "report_regenerated", "vat_report", report.id, report.legal_entity_id,
           version=report.version, snapshot_hash=report.snapshot_hash)  # fmt: skip
    return report


@transaction.atomic
def set_due_date(ctx: WorkspaceContext, entity_id: UUID, report_id: UUID,
                 due: date | None) -> VatReport:  # fmt: skip
    report = _get(ctx, entity_id, report_id, PREPARE, lock=True)
    if report.status == Status.SUPERSEDED:
        raise ConflictError("A superseded report is kept as it was.")
    report.due_date = due
    report.save(update_fields=["due_date"])
    _audit(ctx, "due_date_set", "vat_report", report.id, report.legal_entity_id,
           due_date=due.isoformat() if due else None)  # fmt: skip
    return report


def blockers(ctx: WorkspaceContext, report: VatReport, today: date | None = None) -> list[str]:
    """Why a draft cannot be signed off yet (empty when it can)."""
    found = []
    today = today or timezone.localdate()
    if report.period_end >= today:
        found.append(f"The VAT period ends on {report.period_end.isoformat()}; sign the report "
                     "off after that.")  # fmt: skip
    jurisdiction = get_entity(ctx, report.legal_entity_id).jurisdiction
    now = _take(ctx, report.legal_entity_id, report.period_start, report.period_end, jurisdiction)
    if digest(figures(now)) != report.snapshot_hash:
        found.append("Entries in this period were posted, reversed or changed since the report "
                     "was generated. Regenerate it.")  # fmt: skip
    return found


@transaction.atomic
def sign_off(ctx: WorkspaceContext, entity_id: UUID, report_id: UUID) -> VatReport:
    report = _get(ctx, entity_id, report_id, SIGN_OFF, lock=True)
    if report.status != Status.DRAFT:
        raise ConflictError("Only a draft can be signed off.")
    own = report.created_by_id == ctx.user.id
    if own and not self_approval_allowed(ctx):
        raise PermissionDeniedError("The person who prepared a VAT report cannot also sign it off.")
    problems = blockers(ctx, report)
    if problems:
        raise NotSignableError(" ".join(problems), field_errors={"report": problems})
    now = timezone.now()
    report.status, report.signed_off_by, report.signed_off_at = Status.SIGNED_OFF, ctx.user, now
    report.self_approved = own
    report.save()
    if report.supersedes_id:
        earlier = VatReport.objects.select_for_update().get(id=report.supersedes_id)
        earlier.status, earlier.superseded_at = Status.SUPERSEDED, now
        earlier.save(update_fields=["status", "superseded_at"])
        _audit(ctx, "report_superseded", "vat_report", earlier.id, earlier.legal_entity_id,
               by=str(report.id))  # fmt: skip
    _audit(ctx, "report_signed_off", "vat_report", report.id, report.legal_entity_id,
           version=report.version, snapshot_hash=report.snapshot_hash, self_approved=own,
           net=report.snapshot["totals"]["net"])  # fmt: skip
    return report


@transaction.atomic
def mark_filed(ctx: WorkspaceContext, entity_id: UUID, report_id: UUID, *, filed_on: date,
               reference: str) -> VatReport:  # fmt: skip
    report = _get(ctx, entity_id, report_id, SIGN_OFF, lock=True)
    if report.status != Status.SIGNED_OFF:
        raise ConflictError("Only a signed-off report can be recorded as filed.")
    reference = reference.strip()
    if not reference:
        raise _invalid("reference", "Enter the reference the Tax Department's portal gave.")
    if filed_on > timezone.localdate() or filed_on < report.period_start:
        raise _invalid("filed_on", "Enter the date you filed the return.")
    report.status, report.filed_by, report.filed_on = Status.FILED, ctx.user, filed_on
    report.filing_reference = reference[:100]
    report.save(update_fields=["status", "filed_by", "filed_on", "filing_reference"])
    _audit(ctx, "report_filed", "vat_report", report.id, report.legal_entity_id,
           filed_on=filed_on.isoformat(), reference=report.filing_reference)  # fmt: skip
    return report


@transaction.atomic
def new_version(ctx: WorkspaceContext, entity_id: UUID, report_id: UUID) -> VatReport:
    current = _get(ctx, entity_id, report_id, PREPARE, lock=True)
    if current.status not in (Status.SIGNED_OFF, Status.FILED):
        raise ConflictError("A new version starts from a signed-off or filed report.")
    if VatReport.objects.filter(legal_entity_id=current.legal_entity_id,
                                period_start=current.period_start,
                                version__gt=current.version).exists():  # fmt: skip
        raise ConflictError("A newer version of this report already exists.")
    report = VatReport(tenant=ctx.tenant, legal_entity_id=current.legal_entity_id,
                       period_start=current.period_start, period_end=current.period_end,
                       version=current.version + 1, supersedes=current, created_by=ctx.user,
                       due_date=current.due_date)  # fmt: skip
    _snapshot(ctx, report, get_entity(ctx, entity_id).jurisdiction)
    report.save()
    _audit(ctx, "report_generated", "vat_report", report.id, report.legal_entity_id,
           version=report.version, supersedes=str(current.id),
           snapshot_hash=report.snapshot_hash)  # fmt: skip
    return report


@transaction.atomic
def prepare_settlement(ctx: WorkspaceContext, entity_id: UUID, report_id: UUID) -> UUID:
    """A draft entry, dated the period's last day, that moves the period's input VAT into the
    output VAT account, leaving there the net amount payable (or refundable). It then follows the
    normal approval and posting workflow."""
    report = _get(ctx, entity_id, report_id, PREPARE, lock=True)
    if report.status not in (Status.SIGNED_OFF, Status.FILED):
        raise ConflictError("Prepare the settlement after the report is signed off.")
    if report.settlement_entry_id:
        raise ConflictError("The settlement entry of this report was already prepared.")
    entity = get_entity(ctx, entity_id)
    by_code = {a.code: a for a in account_list(ctx, entity.id)}
    accounts = report.snapshot["accounts"]
    inputs = [(a["code"], Decimal(a["vat"])) for a in accounts
              if a["role"] == "INPUT" and Decimal(a["vat"])]  # fmt: skip
    total = sum((amount for _, amount in inputs), Decimal(0))
    if not total:
        raise ConflictError("There is no input VAT to settle in this period.")
    output = next((a["code"] for a in accounts if a["role"] == "OUTPUT"), None) or next(
        (a.code for a in by_code.values() if a.vat_role == "OUTPUT" and a.is_postable), None
    )
    if output is None:
        raise ConflictError("The entity has no output VAT account to settle into.")
    settle = f"{entity.jurisdiction}:SETTLE:open"
    lines = [LineInput(account_id=by_code[output].id, debit=str(total), vat_code_id=settle,
                       memo="Input VAT of the period")]  # fmt: skip
    for code, amount in inputs:
        credit, debit = (str(amount), "0") if amount > 0 else ("0", str(-amount))
        lines.append(LineInput(account_id=by_code[code].id, debit=debit, credit=credit,
                               vat_code_id=settle, memo="Input VAT of the period"))  # fmt: skip
    if total < 0:  # more credit notes than purchases: reverse the sides of the first line
        lines[0] = LineInput(account_id=by_code[output].id, credit=str(-total),
                             vat_code_id=settle, memo="Input VAT of the period")  # fmt: skip
    entry = create_system_draft(ctx, entity.id, EntryInput(
        accounting_date=report.period_end,
        description=f"VAT settlement {report.period_start.isoformat()} to "
                    f"{report.period_end.isoformat()} (report v{report.version})",
        lines=lines,
    ))  # fmt: skip
    report.settlement_entry_id = entry.id
    report.save(update_fields=["settlement_entry_id"])
    _audit(ctx, "settlement_prepared", "vat_report", report.id, report.legal_entity_id,
           entry_id=str(entry.id), input_vat=str(total))  # fmt: skip
    return entry.id
