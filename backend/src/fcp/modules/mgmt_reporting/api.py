"""Public interface of the ``mgmt_reporting`` module: management report packs (M8).

This is the only part of ``fcp.modules.mgmt_reporting`` that other modules may import.
"""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from django.http import HttpRequest
from ninja import Field, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.modules.tenancy.api import workspace_ctx

from . import services
from .models import ReportPack

__all__ = ["router"]

router = Router(tags=["report packs"])
BASE = "/w/{slug}/entities/{uuid:entity_id}/report-packs"


class PackIn(Schema):
    period_kind: Literal["MONTH", "QUARTER", "YEAR"] = Field(
        description="A month, or the fiscal quarter or fiscal year containing the month"
    )
    month: date = Field(description="Any day of the (last) month the pack reports on")
    title: str = Field(default="", max_length=160, description="Empty: a title from the period")


class TitleIn(Schema):
    title: str = Field(min_length=1, max_length=160)


class NoteIn(Schema):
    note: str = Field(default="", max_length=1000)


class ReturnIn(Schema):
    note: str = Field(min_length=1, max_length=1000, description="What the preparer should change")


class PackOut(Schema):
    id: UUID
    family_id: UUID
    version: int
    supersedes_id: UUID | None
    title: str
    period_kind: str
    period_start: date
    period_end: date
    status: str
    sections: list[str]
    columns: list[str]
    snapshot_hash: str
    watermark: int = Field(description="The last posting included in the pack's figures")
    generated_at: datetime
    created_by_id: UUID
    created_at: datetime
    submitted_at: datetime | None
    reviewed_by_id: UUID | None
    review_note: str
    finalised_at: datetime | None
    superseded_at: datetime | None
    blocks: dict[str, str] = Field(description="Each block's state: ok, empty or denied")


class PackDetailOut(PackOut):
    snapshot: dict[str, Any] = Field(description="Every frozen figure, with its nature")
    blockers: list[str] = Field(description="In review: why it cannot be finalised yet")


def _out(p: ReportPack) -> dict[str, Any]:
    return {
        "id": p.id, "family_id": p.family_id, "version": p.version,
        "supersedes_id": p.supersedes_id, "title": p.title, "period_kind": p.period_kind,
        "period_start": p.period_start, "period_end": p.period_end, "status": p.status,
        "sections": p.sections, "columns": p.columns, "snapshot_hash": p.snapshot_hash,
        "watermark": p.watermark, "generated_at": p.generated_at,
        "created_by_id": p.created_by_id, "created_at": p.created_at,
        "submitted_at": p.submitted_at, "reviewed_by_id": p.reviewed_by_id,
        "review_note": p.review_note, "finalised_at": p.finalised_at,
        "superseded_at": p.superseded_at, "blocks": services.summary(p),
    }  # fmt: skip


@router.get(BASE, response=list[PackOut])
@requires("reports.pack.read")
def list_packs(request: HttpRequest, slug: str, entity_id: UUID) -> list[PackOut]:
    """Every pack of the entity, latest period first, newest version first."""
    ctx = workspace_ctx(request, slug, entity_id)
    return [PackOut(**_out(p)) for p in services.packs(ctx, entity_id)]


@router.post(BASE, response={201: PackDetailOut})
@requires("reports.pack.prepare")
def create_pack(request: HttpRequest, slug: str, entity_id: UUID,
                body: PackIn) -> Status[PackDetailOut]:  # fmt: skip
    """Generate a pack: a draft whose figures are frozen now, under your permissions."""
    ctx = workspace_ctx(request, slug, entity_id)
    p = services.create(ctx, entity_id, kind=body.period_kind, month=body.month,
                        title=body.title)  # fmt: skip
    return Status(201, _detail(ctx, p))


def _detail(ctx: Any, p: ReportPack) -> PackDetailOut:
    stuck = services.blockers(ctx, p) if p.status == services.Status.IN_REVIEW else []
    return PackDetailOut(**_out(p), snapshot=p.snapshot, blockers=stuck)


@router.get(f"{BASE}/{{uuid:pack_id}}", response=PackDetailOut)
@requires("reports.pack.read")
def get_pack(request: HttpRequest, slug: str, entity_id: UUID, pack_id: UUID) -> PackDetailOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _detail(ctx, services.get(ctx, entity_id, pack_id))


@router.post(f"{BASE}/{{uuid:pack_id}}/regenerate", response=PackDetailOut)
@requires("reports.pack.prepare")
def regenerate_pack(request: HttpRequest, slug: str, entity_id: UUID,
                    pack_id: UUID) -> PackDetailOut:  # fmt: skip
    """Take the draft's figures again, now."""
    ctx = workspace_ctx(request, slug, entity_id)
    return _detail(ctx, services.regenerate(ctx, entity_id, pack_id))


@router.put(f"{BASE}/{{uuid:pack_id}}/title", response=PackOut)
@requires("reports.pack.prepare")
def retitle_pack(request: HttpRequest, slug: str, entity_id: UUID, pack_id: UUID,
                 body: TitleIn) -> PackOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return PackOut(**_out(services.retitle(ctx, entity_id, pack_id, body.title)))


@router.post(f"{BASE}/{{uuid:pack_id}}/submit", response=PackDetailOut)
@requires("reports.pack.prepare")
def submit_pack(request: HttpRequest, slug: str, entity_id: UUID,
                pack_id: UUID) -> PackDetailOut:  # fmt: skip
    """Send the draft for review; it no longer changes unless returned."""
    ctx = workspace_ctx(request, slug, entity_id)
    return _detail(ctx, services.submit(ctx, entity_id, pack_id))


@router.post(f"{BASE}/{{uuid:pack_id}}/return", response=PackOut)
@requires("reports.finalise")
def return_pack(request: HttpRequest, slug: str, entity_id: UUID, pack_id: UUID,
                body: ReturnIn) -> PackOut:  # fmt: skip
    """Send the pack back to its preparer as a draft, saying what to change."""
    ctx = workspace_ctx(request, slug, entity_id)
    return PackOut(**_out(services.return_to_preparer(ctx, entity_id, pack_id, body.note)))


@router.post(f"{BASE}/{{uuid:pack_id}}/finalise", response=PackDetailOut)
@requires("reports.finalise")
def finalise_pack(request: HttpRequest, slug: str, entity_id: UUID, pack_id: UUID,
                  body: NoteIn) -> PackDetailOut:  # fmt: skip
    """Make the pack final: it never changes again (409 with the reasons while it cannot)."""
    ctx = workspace_ctx(request, slug, entity_id)
    return _detail(ctx, services.finalise(ctx, entity_id, pack_id, body.note))


@router.post(f"{BASE}/{{uuid:pack_id}}/new-version", response={201: PackDetailOut})
@requires("reports.pack.prepare")
def new_pack_version(request: HttpRequest, slug: str, entity_id: UUID,
                     pack_id: UUID) -> Status[PackDetailOut]:  # fmt: skip
    """Correct a final pack: a new draft version with figures taken now."""
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(201, _detail(ctx, services.new_version(ctx, entity_id, pack_id)))
