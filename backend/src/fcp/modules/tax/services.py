"""VAT periods and VAT period reports (V1-2, #208; ADR-0056; four steps V1-2d, #215, ADR-0060).

- **See**: ``tax.vat.read``. **Prepare** (generate, regenerate, set the due date, propose or
  withdraw an adjustment, start a new version, prepare the settlement entry): ``tax.vat.prepare``.
  **Review**, **send back to draft**, **finalise**, **decide an adjustment**, **record the filing**
  and **choose the VAT periods**: ``tax.vat.sign_off``.
- A report is computed from the posted ledger under the preparer's permissions and frozen. A draft
  can be regenerated; a reviewed report's figures never change.
- **Draft → Reviewed → Finalised → Filed.** Reviewing is refused before the period has ended, while
  the period's figures have changed since the report was generated, and while an adjustment is
  still proposed. Finalising is refused when the figures changed after the review. The reviewer
  and the finaliser are not the preparer, except in a one-person workspace, where it is recorded
  as self-approved.
- **Adjustments** change one box of a draft by an amount, with a reason and evidence; they count
  only once approved, by someone other than their author (except in a one-person workspace).
- **Finalising** records the inclusion of every line in that return; a line is in one return.
- **Filed** records that the owner filed the return on the Tax Department's portal, with its
  reference and evidence. The platform never files anything.
- A correction is a **new version** (an amendment once the earlier one was filed); when it is
  finalised, the earlier version is superseded. Entries posted after a report was prepared show
  as a list of differences; they are never moved into another return automatically.
Every change is audited.
"""

from dataclasses import dataclass
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
from .models import BOXES, VatAdjustment, VatInclusion, VatPeriodScheme, VatReport
from .report import Line, adjusted, compute, digest, figures

READ, PREPARE, SIGN_OFF = "tax.vat.read", "tax.vat.prepare", "tax.vat.sign_off"
Status = VatReport.Status


class NotSignableError(ConflictError):
    code = "tax.vat.not_signable"


DONE = (Status.FINALISED, Status.FILED)


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
        status__in=[Status.REVIEWED, Status.FINALISED, Status.FILED],
    ).exists()  # fmt: skip
    if settled:
        raise _invalid("effective_from", "A report reviewed or finalised for a period on or after "
                       "this date would no longer match its period.")  # fmt: skip
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


def _changed(ctx: WorkspaceContext, report: VatReport) -> dict[str, Any] | None:
    """The period's figures now, when they differ from the report's (else None)."""
    jurisdiction = get_entity(ctx, report.legal_entity_id).jurisdiction
    now = _take(ctx, report.legal_entity_id, report.period_start, report.period_end, jurisdiction)
    return now if digest(figures(now)) != report.snapshot_hash else None


CHANGED = ("Entries in this period were posted, reversed or changed since the report was "
           "generated.")  # fmt: skip


def blockers(ctx: WorkspaceContext, report: VatReport, today: date | None = None) -> list[str]:
    """Why the report cannot take its next step yet (empty when it can)."""
    found: list[str] = []
    if report.status == Status.DRAFT:
        today = today or timezone.localdate()
        if report.period_end >= today:
            found.append(f"The VAT period ends on {report.period_end.isoformat()}; review the "
                         "report after that.")  # fmt: skip
        if _changed(ctx, report) is not None:
            found.append(f"{CHANGED} Regenerate it.")
        if report.adjustments.filter(status=VatAdjustment.Status.PROPOSED).exists():
            found.append("Approve or reject every proposed adjustment first.")
    elif report.status == Status.REVIEWED and _changed(ctx, report) is not None:
        found.append(f"{CHANGED} Send it back to draft and regenerate it.")
    return found


def _check_person(ctx: WorkspaceContext, report: VatReport, step: str) -> bool:
    """True when the preparer takes this step themself (allowed only in a one-person workspace)."""
    own = report.created_by_id == ctx.user.id
    if own and not self_approval_allowed(ctx):
        raise PermissionDeniedError(f"The person who prepared a VAT report cannot also {step} it.")
    return own


@transaction.atomic
def review(ctx: WorkspaceContext, entity_id: UUID, report_id: UUID) -> VatReport:
    report = _get(ctx, entity_id, report_id, SIGN_OFF, lock=True)
    if report.status != Status.DRAFT:
        raise ConflictError("Only a draft can be reviewed.")
    own = _check_person(ctx, report, "review")
    problems = blockers(ctx, report)
    if problems:
        raise NotSignableError(" ".join(problems), field_errors={"report": problems})
    report.status, report.reviewed_by, report.reviewed_at = (
        Status.REVIEWED,
        ctx.user,
        timezone.now(),
    )
    report.self_approved, report.review_note = own, ""
    report.save()
    final = final_return(report)
    _audit(ctx, "report_reviewed", "vat_report", report.id, report.legal_entity_id,
           version=report.version, snapshot_hash=report.snapshot_hash, self_approved=own,
           box_5=final["boxes"][4]["amount"] if final else None)  # fmt: skip
    return report


@transaction.atomic
def reopen(ctx: WorkspaceContext, entity_id: UUID, report_id: UUID, note: str) -> VatReport:
    """A reviewed report back to draft, with the reason; its review is cleared."""
    report = _get(ctx, entity_id, report_id, SIGN_OFF, lock=True)
    if report.status != Status.REVIEWED:
        raise ConflictError("Only a reviewed report can be sent back to draft.")
    note = note.strip()
    if not note:
        raise _invalid("note", "Say why the report goes back to draft.")
    reviewer = report.reviewed_by_id
    report.status, report.reviewed_by, report.reviewed_at = Status.DRAFT, None, None
    report.self_approved, report.review_note = False, note[:500]
    report.save()
    _audit(ctx, "report_reopened", "vat_report", report.id, report.legal_entity_id,
           note=report.review_note, reviewed_by=str(reviewer))  # fmt: skip
    return report


@transaction.atomic
def finalise(ctx: WorkspaceContext, entity_id: UUID, report_id: UUID) -> VatReport:
    report = _get(ctx, entity_id, report_id, SIGN_OFF, lock=True)
    if report.status != Status.REVIEWED:
        raise ConflictError("Review the report before finalising it.")
    own = _check_person(ctx, report, "finalise")
    problems = blockers(ctx, report)
    if problems:
        raise NotSignableError(" ".join(problems), field_errors={"report": problems})
    now = timezone.now()
    report.status, report.finalised_by, report.finalised_at = Status.FINALISED, ctx.user, now
    report.self_approved = report.self_approved or own
    report.save()
    if report.supersedes_id:
        earlier = VatReport.objects.select_for_update().get(id=report.supersedes_id)
        earlier.status, earlier.superseded_at = Status.SUPERSEDED, now
        earlier.save(update_fields=["status", "superseded_at"])
        VatInclusion.objects.filter(report=earlier, active=True).update(active=False)
        _audit(ctx, "report_superseded", "vat_report", earlier.id, earlier.legal_entity_id,
               by=str(report.id))  # fmt: skip
    included = _include(ctx, report)
    final = final_return(report)
    _audit(ctx, "report_finalised", "vat_report", report.id, report.legal_entity_id,
           version=report.version, snapshot_hash=report.snapshot_hash, self_approved=own,
           lines_included=included, net=report.snapshot["totals"]["net"],
           box_5=final["boxes"][4]["amount"] if final else None)  # fmt: skip
    return report


def _include(ctx: WorkspaceContext, report: VatReport) -> int:
    """Record that every line of the return is in it; refused if one is in another return."""
    rows = {ln["line_id"]: ln["entry_id"] for ln in report.snapshot["lines"]
            if ln["kind"] != "SETTLEMENT"}  # fmt: skip
    taken = VatInclusion.objects.filter(active=True, line_id__in=list(rows)).exclude(report=report)
    if taken.exists():
        refs = sorted({ln["entry_ref"] for ln in report.snapshot["lines"]
                       if ln["line_id"] in {str(t.line_id) for t in taken}})  # fmt: skip
        raise ConflictError(f"These entries are already in another return: {', '.join(refs)}.")
    VatInclusion.objects.bulk_create([
        VatInclusion(tenant=ctx.tenant, report=report, line_id=line, entry_id=entry)
        for line, entry in rows.items()
    ])  # fmt: skip
    return len(rows)


@transaction.atomic
def mark_filed(ctx: WorkspaceContext, entity_id: UUID, report_id: UUID, *, filed_on: date,
               reference: str, evidence: str) -> VatReport:  # fmt: skip
    report = _get(ctx, entity_id, report_id, SIGN_OFF, lock=True)
    if report.status != Status.FINALISED:
        raise ConflictError("Only a finalised report can be recorded as filed.")
    reference, evidence = reference.strip(), evidence.strip()
    if not reference:
        raise _invalid("reference", "Enter the reference the Tax Department's portal gave.")
    if not evidence:
        raise _invalid("evidence", "Say where the portal's acknowledgement is kept, for example "
                       "'acknowledgement PDF saved in Documents'.")  # fmt: skip
    if filed_on > timezone.localdate() or filed_on < report.period_start:
        raise _invalid("filed_on", "Enter the date you filed the return.")
    report.status, report.filed_by, report.filed_on = Status.FILED, ctx.user, filed_on
    report.filing_reference, report.filing_evidence = reference[:100], evidence[:500]
    report.save(update_fields=["status", "filed_by", "filed_on", "filing_reference",
                               "filing_evidence"])  # fmt: skip
    _audit(ctx, "report_filed", "vat_report", report.id, report.legal_entity_id,
           filed_on=filed_on.isoformat(), reference=report.filing_reference,
           evidence=report.filing_evidence)  # fmt: skip
    return report


@transaction.atomic
def new_version(ctx: WorkspaceContext, entity_id: UUID, report_id: UUID) -> VatReport:
    """A correction of a finalised or filed report: a new draft from the books as they are now.
    The earlier version's approved adjustments are carried over as proposals, to be decided
    again."""
    current = _get(ctx, entity_id, report_id, PREPARE, lock=True)
    if current.status not in DONE:
        raise ConflictError("A new version starts from a finalised or filed report.")
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
    carried = [
        VatAdjustment(tenant=ctx.tenant, report=report, box=a.box, amount=a.amount,
                      reason=a.reason, evidence=a.evidence, created_by=ctx.user)
        for a in current.adjustments.filter(status=VatAdjustment.Status.APPROVED)
    ]  # fmt: skip
    VatAdjustment.objects.bulk_create(carried)
    _audit(ctx, "report_generated", "vat_report", report.id, report.legal_entity_id,
           version=report.version, supersedes=str(current.id),
           amends_filed=current.status == Status.FILED, adjustments_carried=len(carried),
           snapshot_hash=report.snapshot_hash)  # fmt: skip
    return report


# --- adjustments ---------------------------------------------------------------------------------


def _adjustment(report: VatReport, adjustment_id: UUID) -> VatAdjustment:
    found = report.adjustments.select_for_update().filter(id=adjustment_id).first()
    if found is None:
        raise NotFoundError("Adjustment not found.")
    return found


@dataclass(frozen=True)
class AdjustmentInput:
    box: str
    amount: Decimal
    reason: str
    evidence: str


@transaction.atomic
def propose_adjustment(ctx: WorkspaceContext, entity_id: UUID, report_id: UUID,
                       data: AdjustmentInput) -> VatAdjustment:  # fmt: skip
    box, amount, reason, evidence = data.box, data.amount, data.reason, data.evidence
    report = _get(ctx, entity_id, report_id, PREPARE, lock=True)
    if report.status != Status.DRAFT:
        raise ConflictError("Adjustments are made on a draft. Send the report back to draft or "
                            "start a new version.")  # fmt: skip
    if not report.snapshot.get("return"):
        raise ConflictError("Regenerate the report first, so that it has its boxes.")
    if box not in BOXES:
        raise _invalid("box", "Choose a box to adjust: Boxes 3 and 5 follow from the others.")
    if amount == 0 or amount != amount.quantize(Decimal("0.01")):
        raise _invalid("amount", "Enter an amount in euros and cents, not zero.")
    reason, evidence = reason.strip(), evidence.strip()
    if not reason:
        raise _invalid("reason", "Say why the box is adjusted.")
    if not evidence:
        raise _invalid("evidence", "Say what supports the adjustment, for example an adviser's "
                       "letter or a document in Documents.")  # fmt: skip
    made = VatAdjustment.objects.create(tenant=ctx.tenant, report=report, box=box, amount=amount,
                                        reason=reason[:500], evidence=evidence[:500],
                                        created_by=ctx.user)  # fmt: skip
    _audit(ctx, "adjustment_proposed", "vat_adjustment", made.id, report.legal_entity_id,
           report=str(report.id), box=box, amount=str(amount), reason=made.reason,
           evidence=made.evidence)  # fmt: skip
    return made


@transaction.atomic
def decide_adjustment(
    ctx: WorkspaceContext, entity_id: UUID, report_id: UUID, adjustment_id: UUID, *,
    approve: bool, note: str = "",
) -> VatAdjustment:  # fmt: skip
    """Approve (``tax.vat.sign_off``, not the author) or reject an adjustment; its author may
    withdraw (reject) their own with ``tax.vat.prepare``."""
    entity = get_entity(ctx, entity_id, READ)
    report = _get(ctx, entity.id, report_id, READ, lock=True)
    adjustment = _adjustment(report, adjustment_id)
    own = adjustment.created_by_id == ctx.user.id
    if approve or not own:
        get_entity(ctx, entity.id, SIGN_OFF)
    else:
        get_entity(ctx, entity.id, PREPARE)
    if report.status != Status.DRAFT or adjustment.status != VatAdjustment.Status.PROPOSED:
        raise ConflictError("Only a proposed adjustment of a draft can be decided.")
    if approve and own and not self_approval_allowed(ctx):
        raise PermissionDeniedError("The person who proposed an adjustment cannot also approve it.")
    adjustment.status = VatAdjustment.Status.APPROVED if approve else VatAdjustment.Status.REJECTED
    adjustment.decided_by, adjustment.decided_at = ctx.user, timezone.now()
    adjustment.decision_note, adjustment.self_approved = note.strip()[:500], approve and own
    adjustment.save()
    _audit(ctx, "adjustment_approved" if approve else "adjustment_rejected", "vat_adjustment",
           adjustment.id, report.legal_entity_id, report=str(report.id), box=adjustment.box,
           amount=str(adjustment.amount), self_approved=adjustment.self_approved,
           note=adjustment.decision_note)  # fmt: skip
    return adjustment


def final_return(report: VatReport) -> dict[str, Any] | None:
    """The return after its approved adjustments (None for a report without boxes)."""
    found = report.snapshot.get("return")
    if not found:
        return None
    approved = report.adjustments.filter(status=VatAdjustment.Status.APPROVED).order_by(
        "created_at"
    )
    return adjusted(found, [(a.box, a.amount) for a in approved])


# --- differences ---------------------------------------------------------------------------------


def differences(ctx: WorkspaceContext, report: VatReport) -> dict[str, Any]:
    """What the books say now that the report does not: lines posted, or reversed, in the period
    after it was prepared, with the change to each box. Shown, never applied: a correction is a
    new version of the report."""
    now = _changed(ctx, report)
    if now is None:
        return {"changed": False, "added": [], "removed": [], "boxes": {}}
    before = {ln["line_id"]: ln for ln in report.snapshot["lines"]}
    after = {ln["line_id"]: ln for ln in now["lines"]}
    added = [ln for key, ln in after.items() if key not in before]
    removed = [ln for key, ln in before.items() if key not in after]
    delta: dict[str, Decimal] = {}
    for sign, rows in ((1, added), (-1, removed)):
        for ln in rows:
            for box, amount in ln.get("boxes", {}).items():
                delta[box] = delta.get(box, Decimal(0)) + sign * Decimal(amount)
    if delta:
        delta["3"] = delta.get("1", Decimal(0)) + delta.get("2", Decimal(0))
        delta["5"] = delta["3"] - delta.get("4", Decimal(0))
    return {"changed": True, "added": added, "removed": removed,
            "boxes": {b: f"{v:.2f}" for b, v in delta.items() if v}}  # fmt: skip


def previous_version(report: VatReport) -> dict[str, Any] | None:
    """For a new version: the version it corrects and the change to each box since."""
    if not report.supersedes_id:
        return None
    earlier = VatReport.objects.get(id=report.supersedes_id)
    before, after = final_return(earlier), final_return(report)
    change = {}
    if before and after:
        old = {b["box"]: Decimal(b["exact"]) for b in before["boxes"]}
        change = {b["box"]: f"{Decimal(b['exact']) - old[b['box']]:.2f}" for b in after["boxes"]
                  if Decimal(b["exact"]) != old[b["box"]]}  # fmt: skip
    return {"id": earlier.id, "version": earlier.version, "status": earlier.status,
            "filed_on": earlier.filed_on, "filing_reference": earlier.filing_reference,
            "boxes": change}  # fmt: skip


@transaction.atomic
def prepare_settlement(ctx: WorkspaceContext, entity_id: UUID, report_id: UUID) -> UUID:
    """A draft entry, dated the period's last day, that moves the period's input VAT into the
    output VAT account, leaving there the net amount payable (or refundable). It then follows the
    normal approval and posting workflow."""
    report = _get(ctx, entity_id, report_id, PREPARE, lock=True)
    if report.status not in DONE:
        raise ConflictError("Prepare the settlement after the report is finalised.")
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
