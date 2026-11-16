"""Public interface of the ``documents`` module and its HTTP routes (M2-4).

Routes are entity-scoped: ``/api/w/{slug}/entities/{entity_id}/...``.
"""

from datetime import datetime
from urllib.parse import quote
from uuid import UUID

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from ninja import Field, File, Form, Query, Router, Schema, Status
from ninja.files import UploadedFile

from fcp.core.api.permissions import requires
from fcp.modules.tenancy.api import workspace_ctx

from . import services
from .models import Document
from .services import Target

__all__: list[str] = ["router"]

router = Router(tags=["documents"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"


class LinkOut(Schema):
    id: UUID
    entry_id: UUID | None
    line_id: UUID | None


class DocumentOut(Schema):
    id: UUID
    filename: str
    content_type: str
    size: int
    sha256: str
    created_at: datetime
    uploaded_by_id: UUID
    links: list[LinkOut]


def _out(d: Document) -> DocumentOut:
    return DocumentOut(
        id=d.id,
        filename=d.filename,
        content_type=d.content_type,
        size=d.size,
        sha256=d.sha256,
        created_at=d.created_at,
        uploaded_by_id=d.uploaded_by_id,
        links=[LinkOut(id=ln.id, entry_id=ln.entry_id, line_id=ln.line_id) for ln in d.links.all()],
    )


def _target(entry_id: UUID | None, line_id: UUID | None) -> Target | None:
    return Target(entry_id, line_id) if entry_id or line_id else None


@router.post(f"{BASE}/documents", response={200: DocumentOut, 201: DocumentOut})
@requires("documents.upload")
def upload_document(
    request: HttpRequest,
    slug: str,
    entity_id: UUID,
    file: File[UploadedFile],
    entry_id: Form[UUID | None] = None,
    line_id: Form[UUID | None] = None,
) -> Status[DocumentOut]:
    """Upload a document (at most 10 MB; PDF, PNG, JPEG, XLSX, CSV, TXT, XML), optionally
    attached to an entry or an open item. The content must match the extension and pass the virus
    scan. The same file again returns the existing document (200)."""
    ctx = workspace_ctx(request, slug, entity_id)
    data = file.read(settings.DOCUMENTS_MAX_BYTES + 1)
    document, created = services.upload(
        ctx,
        entity_id,
        filename=file.name or "document",
        data=data,
        target=_target(entry_id, line_id),
    )
    document.refresh_from_db()
    return Status(201 if created else 200, _out(document))


class DocumentsQuery(Schema):
    entry_id: UUID | None = None
    line_id: UUID | None = None


@router.get(f"{BASE}/documents", response=list[DocumentOut])
@requires("documents.read")
def documents(
    request: HttpRequest, slug: str, entity_id: UUID, q: Query[DocumentsQuery]
) -> list[DocumentOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [
        _out(d) for d in services.list_documents(ctx, entity_id, _target(q.entry_id, q.line_id))
    ]


@router.get(f"{BASE}/documents/{{uuid:document_id}}", response=DocumentOut)
@requires("documents.read")
def document(request: HttpRequest, slug: str, entity_id: UUID, document_id: UUID) -> DocumentOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _out(services.get_document(ctx, entity_id, document_id))


@router.get(f"{BASE}/documents/{{uuid:document_id}}/content")
@requires("documents.read")
def document_content(
    request: HttpRequest, slug: str, entity_id: UUID, document_id: UUID
) -> HttpResponse:
    """The file, always as a download (never rendered inline), with the sniffed content type."""
    ctx = workspace_ctx(request, slug, entity_id)
    doc, data = services.content(ctx, entity_id, document_id)
    response = HttpResponse(data, content_type=doc.content_type)
    ascii_name = doc.filename.encode("ascii", "replace").decode().replace('"', "'")
    response["Content-Disposition"] = (
        f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(doc.filename)}"
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


class LinkIn(Schema):
    entry_id: UUID | None = None
    line_id: UUID | None = Field(default=None, description="A posted line on a control account")


@router.post(f"{BASE}/documents/{{uuid:document_id}}/links", response={201: LinkOut})
@requires("documents.link")
def link_document(
    request: HttpRequest, slug: str, entity_id: UUID, document_id: UUID, payload: LinkIn
) -> Status[LinkOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    made = services.link(ctx, entity_id, document_id, Target(payload.entry_id, payload.line_id))
    return Status(201, LinkOut(id=made.id, entry_id=made.entry_id, line_id=made.line_id))


@router.delete(f"{BASE}/document-links/{{uuid:link_id}}", response={204: None})
@requires("documents.link")
def unlink_document(
    request: HttpRequest, slug: str, entity_id: UUID, link_id: UUID
) -> Status[None]:
    """Detach a document (the document itself is kept: documents are never deleted)."""
    ctx = workspace_ctx(request, slug, entity_id)
    services.unlink(ctx, entity_id, link_id)
    return Status(204, None)
