"""Document vault services: upload pipeline, download, links (M2-4, ADR-0016).

Upload pipeline, in this order, all before anything is stored:
1. permission and size (``DOCUMENTS_MAX_BYTES``);
2. type: the extension is on the allowlist and the content really is that type (sniffed);
3. the same content in the same legal entity is the same document (idempotent);
4. antivirus (ClamAV, fails closed): malware is refused and only its signature name is audited;
5. stored under the tenant's prefix (SSE-KMS with a tenant context when deployed), then recorded.

Nothing here logs or audits document content: events carry the name, type, size and SHA-256.
"""

import hashlib
from dataclasses import dataclass
from uuid import UUID

from django.conf import settings
from django.db import transaction

from fcp.core.errors import NotFoundError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.ledger.api import JournalEntry, JournalLine
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from . import scanner, sniff, storage
from .models import Document, DocumentLink


class DocumentRejectedError(ValidationFailedError):
    code = "documents.malware_detected"
    title = "The file was rejected by the virus scanner"


class DocumentTooLargeError(ValidationFailedError):
    code = "documents.too_large"
    title = "The file is too large"


def _audit(
    ctx: WorkspaceContext,
    entity_id: UUID,
    action: str,
    subject_id: object,
    changes: dict[str, object],
) -> None:
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action=action,
        subject_type="document",
        subject_id=subject_id,
        entity_id=entity_id,
        changes=changes,
    )


@dataclass(frozen=True)
class Target:
    """What a document is attached to: a journal entry, or an open item (a posted line on a
    control account)."""

    entry_id: UUID | None = None
    line_id: UUID | None = None


def _check_target(entity_id: UUID, target: Target) -> None:
    if (target.entry_id is None) == (target.line_id is None):
        raise ValidationFailedError(
            "Attach the document to one entry or one open item.",
            field_errors={"target": ["exactly one"]},
        )
    if target.entry_id is not None:
        if not JournalEntry.objects.filter(legal_entity_id=entity_id, id=target.entry_id).exists():
            raise NotFoundError("Journal entry not found.")
        return
    line_id: UUID = target.line_id  # type: ignore[assignment]  # exactly one is set (above)
    line = (
        JournalLine.objects.select_related("entry", "account")
        .filter(id=line_id, entry__legal_entity_id=entity_id)
        .first()
    )
    if line is None:
        raise NotFoundError("Open item not found.")
    if line.entry.status != JournalEntry.Status.POSTED or not line.account.control_type:
        raise ValidationFailedError(
            "Documents attach to open items: posted lines on receivables or payables.",
            field_errors={"line_id": ["not an open item"]},
        )


def upload(
    ctx: WorkspaceContext,
    entity_id: UUID,
    *,
    filename: str,
    data: bytes,
    target: Target | None = None,
) -> tuple[Document, bool]:
    """Store a document (returns it and whether it is new), optionally attaching it."""
    entity = get_entity(ctx, entity_id, "documents.upload")
    if target is not None:
        get_entity(ctx, entity_id, "documents.link")
        _check_target(entity.id, target)
    name = sniff.safe_filename(filename)
    if not data or len(data) > settings.DOCUMENTS_MAX_BYTES:
        raise DocumentTooLargeError(
            f"Documents must be between 1 byte and "
            f"{settings.DOCUMENTS_MAX_BYTES // (1024 * 1024)} MB.",
            field_errors={"file": ["size"]},
        )
    content_type = sniff.check(name, data)
    digest = hashlib.sha256(data).hexdigest()
    document = Document.objects.filter(legal_entity=entity, sha256=digest).first()
    created = document is None
    if document is None:
        result = scanner.scan(data)
        if not result.clean:
            # Recorded outside any savepoint, so the refusal stays in the audit trail.
            _audit(
                ctx,
                entity.id,
                "documents.rejected_malware",
                digest,
                {
                    "filename": name,
                    "size": len(data),
                    "sha256": digest,
                    "signature": result.signature,
                },
            )
            raise DocumentRejectedError(
                f"The virus scanner found {result.signature} in this file, so it was not stored.",
                field_errors={"file": ["malware"]},
            )
    with transaction.atomic():
        if document is None:
            document = _store(ctx, entity.id, name, content_type, data, digest)
        if target is not None:
            link(ctx, entity.id, document.id, target)
    return document, created


def _store(
    ctx: WorkspaceContext, entity_id: UUID, name: str, content_type: str, data: bytes, digest: str
) -> Document:
    document = Document(
        tenant=ctx.tenant,
        legal_entity_id=entity_id,
        filename=name,
        content_type=content_type,
        size=len(data),
        sha256=digest,
        uploaded_by=ctx.user,
    )
    document.storage_key = storage.document_key(ctx.tenant.id, document.id)
    storage.put(ctx.tenant.id, document.storage_key, data, content_type)
    document.save(force_insert=True)
    _audit(
        ctx,
        entity_id,
        "documents.uploaded",
        document.id,
        {"filename": name, "content_type": content_type, "size": len(data), "sha256": digest},
    )
    return document


def list_documents(
    ctx: WorkspaceContext, entity_id: UUID, target: Target | None = None
) -> list[Document]:
    entity = get_entity(ctx, entity_id, "documents.read")
    documents = Document.objects.filter(legal_entity=entity)
    if target is not None and target.entry_id:
        documents = documents.filter(links__entry_id=target.entry_id)
    if target is not None and target.line_id:
        documents = documents.filter(links__line_id=target.line_id)
    return list(documents.prefetch_related("links").order_by("-created_at").distinct())


def get_document(ctx: WorkspaceContext, entity_id: UUID, document_id: UUID) -> Document:
    entity = get_entity(ctx, entity_id, "documents.read")
    document = (
        Document.objects.prefetch_related("links")
        .filter(legal_entity=entity, id=document_id)
        .first()
    )
    if document is None:
        raise NotFoundError("Document not found.")
    return document


def content(ctx: WorkspaceContext, entity_id: UUID, document_id: UUID) -> tuple[Document, bytes]:
    """The stored file. Reads are audited: these are confidential client documents."""
    document = get_document(ctx, entity_id, document_id)
    data = storage.get(ctx.tenant.id, document.storage_key)
    if hashlib.sha256(data).hexdigest() != document.sha256:
        raise storage.StorageUnavailableError("The stored document failed its integrity check.")
    _audit(
        ctx,
        document.legal_entity_id,
        "documents.downloaded",
        document.id,
        {"filename": document.filename},
    )
    return document, data


@transaction.atomic
def link(ctx: WorkspaceContext, entity_id: UUID, document_id: UUID, target: Target) -> DocumentLink:
    entity = get_entity(ctx, entity_id, "documents.link")
    document = get_document(ctx, entity.id, document_id)
    _check_target(entity.id, target)
    existing = DocumentLink.objects.filter(
        document=document, entry_id=target.entry_id, line_id=target.line_id
    ).first()
    if existing is not None:
        return existing
    created = DocumentLink.objects.create(
        tenant=ctx.tenant,
        document=document,
        entry_id=target.entry_id,
        line_id=target.line_id,
        created_by=ctx.user,
    )
    _audit(
        ctx,
        entity.id,
        "documents.linked",
        document.id,
        {"entry_id": target.entry_id, "line_id": target.line_id},
    )
    return created


@transaction.atomic
def unlink(ctx: WorkspaceContext, entity_id: UUID, link_id: UUID) -> None:
    entity = get_entity(ctx, entity_id, "documents.link")
    found = DocumentLink.objects.filter(id=link_id, document__legal_entity=entity).first()
    if found is None:
        raise NotFoundError("Link not found.")
    _audit(
        ctx,
        entity.id,
        "documents.unlinked",
        found.document_id,
        {"entry_id": found.entry_id, "line_id": found.line_id},
    )
    found.delete()
