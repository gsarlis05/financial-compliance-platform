"""Report packs: generate, review, finalise and version (M8-1, brief 22 §3, AC-MR1 to AC-MR3).

- **See** packs: ``reports.pack.read``. **Prepare** (generate, regenerate, retitle, submit, start a
  new version): ``reports.pack.prepare``. **Review** (return to the preparer or finalise):
  ``reports.finalise``, and the reviewer is never the preparer (also enforced by the database).
- **Generating** freezes a snapshot under the preparer's own permissions (``snapshot.take``).
  A draft can be regenerated; a pack in review or final never changes.
- **Finalising** is refused, with what to do, while a variance above the budget's thresholds has
  no explanation in the snapshot, or while the period's figures have changed since the snapshot
  was taken (an entry dated in or before the period was posted since). Postings for later months
  do not block a pack.
- A correction is a **new version** of a final pack: a fresh draft that names the version it
  supersedes; when it is finalised, the earlier version becomes superseded.
Every change is audited.
"""

from datetime import date
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from fcp.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from fcp.core.ids import uuid7
from fcp.modules.audit_log.api import record as audit
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from . import snapshot
from .models import ReportPack

READ, PREPARE, FINALISE = "reports.pack.read", "reports.pack.prepare", "reports.finalise"
Status = ReportPack.Status
SECTIONS = ("overview", "profitability", "cash", "working_capital", "budget", "kpis", "forecast",
            "risks", "goals", "commentary")  # fmt: skip
COLUMNS = ("actual", "budget", "original_budget", "forecast", "prior_year", "variance")


class PackNotFinalisableError(ConflictError):
    code = "mgmt_reporting.not_finalisable"


def _audit(ctx: WorkspaceContext, action: str, p: ReportPack, **changes: object) -> None:
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id,
          action=f"mgmt_reporting.pack_{action}", subject_type="report_pack", subject_id=p.id,
          entity_id=p.legal_entity_id,
          changes={"title": p.title, "version": p.version, "status": p.status,
                   "period": f"{p.period_start}/{p.period_end}", **changes})  # fmt: skip


def packs(ctx: WorkspaceContext, entity_id: UUID) -> list[ReportPack]:
    entity = get_entity(ctx, entity_id, READ).id
    return list(ReportPack.objects.filter(legal_entity_id=entity)
                .order_by("-period_end", "family_id", "-version"))  # fmt: skip


def get(ctx: WorkspaceContext, entity_id: UUID, pack_id: UUID,
        permission: str = READ) -> ReportPack:  # fmt: skip
    entity = get_entity(ctx, entity_id, permission).id
    found = ReportPack.objects.filter(legal_entity_id=entity, id=pack_id).first()
    if found is None:
        raise NotFoundError("Report pack not found.")
    return found


def _locked(ctx: WorkspaceContext, entity_id: UUID, pack_id: UUID, permission: str,
            status: str) -> ReportPack:  # fmt: skip
    p = get(ctx, entity_id, pack_id, permission)
    locked = ReportPack.objects.select_for_update().get(id=p.id)
    if locked.status != status:
        what = {"DRAFT": "a draft", "IN_REVIEW": "in review"}.get(str(status), str(status))
        raise ConflictError(f"This needs a pack that is {what}; this one is "
                            f"{locked.status.lower().replace('_', ' ')}.")  # fmt: skip
    return locked


def _fill(ctx: WorkspaceContext, p: ReportPack, taken: snapshot.Snapshot) -> None:
    p.snapshot, p.snapshot_hash, p.watermark = taken.data, taken.digest, taken.watermark
    p.generated_at, p.generated_by = timezone.now(), ctx.user


def _title(p: snapshot.Period, title: str) -> str:
    if title.strip():
        return title.strip()
    label = {"MONTH": p.start.strftime("%B %Y"),
             "QUARTER": f"{p.start:%b %Y} to {p.end:%b %Y}",
             "YEAR": f"Fiscal year {p.start:%Y}/{p.end:%y}"}[p.kind]  # fmt: skip
    return f"Management pack, {label}"


@transaction.atomic
def create(ctx: WorkspaceContext, entity_id: UUID, *, kind: str, month: date,
           title: str = "") -> ReportPack:  # fmt: skip
    entity = get_entity(ctx, entity_id, PREPARE).id
    period = snapshot.period_of(ctx, entity, kind, month)
    taken = snapshot.take(ctx, entity, period)
    p = ReportPack(tenant=ctx.tenant, legal_entity_id=entity, family_id=uuid7(), version=1,
                   title=_title(period, title), period_kind=kind, period_start=period.start,
                   period_end=period.end, sections=list(SECTIONS), columns=list(COLUMNS),
                   created_by=ctx.user)  # fmt: skip
    _fill(ctx, p, taken)
    p.save()
    _audit(ctx, "generated", p, snapshot_hash=p.snapshot_hash, watermark=p.watermark)
    return p


def _period(p: ReportPack) -> snapshot.Period:
    return snapshot.Period(p.period_kind, p.period_start, p.period_end)


@transaction.atomic
def regenerate(ctx: WorkspaceContext, entity_id: UUID, pack_id: UUID) -> ReportPack:
    p = _locked(ctx, entity_id, pack_id, PREPARE, Status.DRAFT)
    before = p.snapshot_hash
    _fill(ctx, p, snapshot.take(ctx, p.legal_entity_id, _period(p)))
    p.save()
    _audit(ctx, "regenerated", p, previous_hash=before, snapshot_hash=p.snapshot_hash)
    return p


@transaction.atomic
def retitle(ctx: WorkspaceContext, entity_id: UUID, pack_id: UUID, title: str) -> ReportPack:
    p = _locked(ctx, entity_id, pack_id, PREPARE, Status.DRAFT)
    before, p.title = p.title, title.strip()
    p.save(update_fields=["title"])
    _audit(ctx, "retitled", p, previous_title=before)
    return p


@transaction.atomic
def submit(ctx: WorkspaceContext, entity_id: UUID, pack_id: UUID) -> ReportPack:
    p = _locked(ctx, entity_id, pack_id, PREPARE, Status.DRAFT)
    p.status, p.submitted_at, p.review_note = Status.IN_REVIEW, timezone.now(), ""
    p.save()
    _audit(ctx, "submitted", p)
    return p


@transaction.atomic
def return_to_preparer(ctx: WorkspaceContext, entity_id: UUID, pack_id: UUID,
                       note: str) -> ReportPack:  # fmt: skip
    p = _locked(ctx, entity_id, pack_id, FINALISE, Status.IN_REVIEW)
    p.status, p.submitted_at, p.review_note = Status.DRAFT, None, note.strip()
    p.save()
    _audit(ctx, "returned", p, note=p.review_note)
    return p


def blockers(ctx: WorkspaceContext, p: ReportPack) -> list[str]:
    """Why the pack cannot be finalised now (empty: it can)."""
    found = []
    missing = snapshot.missing_explanations(p.snapshot)
    if missing:
        shown = ", ".join(missing[:10]) + (" …" if len(missing) > 10 else "")
        found.append(f"These variances need an explanation before the pack is final: {shown}. "
                     "Explain them in the budget review, return the pack to draft and "
                     "regenerate it.")  # fmt: skip
    frozen = p.snapshot["blocks"]["statements"]
    if frozen["status"] == "ok":
        now = snapshot.statements(ctx, p.legal_entity_id, _period(p))
        if now["statements"] != frozen["data"]["statements"]:
            found.append("Entries in or before this period were posted after the pack was "
                         "generated, so its figures have changed. Return it to draft and "
                         "regenerate it.")  # fmt: skip
    return found


@transaction.atomic
def finalise(ctx: WorkspaceContext, entity_id: UUID, pack_id: UUID,
             note: str = "") -> ReportPack:  # fmt: skip
    p = _locked(ctx, entity_id, pack_id, FINALISE, Status.IN_REVIEW)
    if p.created_by_id == ctx.user.id:
        raise PermissionDeniedError("The person who prepared a pack cannot also finalise it.")
    problems = blockers(ctx, p)
    if problems:
        raise PackNotFinalisableError(" ".join(problems), field_errors={"pack": problems})
    now = timezone.now()
    p.status, p.reviewed_by, p.finalised_at = Status.FINAL, ctx.user, now
    p.review_note = note.strip()
    p.save()
    if p.supersedes_id:
        earlier = ReportPack.objects.select_for_update().get(id=p.supersedes_id)
        earlier.status, earlier.superseded_at = Status.SUPERSEDED, now
        earlier.save(update_fields=["status", "superseded_at"])
        _audit(ctx, "superseded", earlier, by=str(p.id))
    _audit(ctx, "finalised", p, snapshot_hash=p.snapshot_hash)
    return p


@transaction.atomic
def new_version(ctx: WorkspaceContext, entity_id: UUID, pack_id: UUID) -> ReportPack:
    final = _locked(ctx, entity_id, pack_id, PREPARE, Status.FINAL)
    latest = ReportPack.objects.filter(family_id=final.family_id).aggregate(v=Max("version"))["v"]
    if latest != final.version:
        raise ConflictError("A newer version of this pack already exists; correct that one.")
    p = ReportPack(tenant=ctx.tenant, legal_entity_id=final.legal_entity_id,
                   family_id=final.family_id, version=final.version + 1, supersedes=final,
                   title=final.title, period_kind=final.period_kind,
                   period_start=final.period_start, period_end=final.period_end,
                   sections=final.sections, columns=final.columns,
                   created_by=ctx.user)  # fmt: skip
    _fill(ctx, p, snapshot.take(ctx, final.legal_entity_id, _period(final)))
    p.save()
    _audit(ctx, "versioned", p, supersedes=str(final.id), snapshot_hash=p.snapshot_hash)
    return p


def summary(p: ReportPack) -> dict[str, Any]:
    """The state of each block, for lists and checks."""
    return {k: b["status"] for k, b in p.snapshot.get("blocks", {}).items()}
