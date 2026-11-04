"""Document vault (M2-4, ADR-0016).

- ``Document``: one stored file (content in object storage under the tenant's prefix). Metadata
  only here: name, sniffed type, size, SHA-256. Documents are evidence: they are immutable and
  users cannot delete them (a database trigger refuses DELETE and any change). Retention and
  disposal are a later platform job (Cyprus bookkeeping retention: at least six years).
- ``DocumentLink``: a document attached to a journal entry or to an open item (a posted line on
  a control account). Exactly one target per link; links can be removed (the document stays).
"""

from django.conf import settings
from django.db import models

from fcp.core.db.models import TenantOwned

LEGAL_ENTITY = "tenancy.LegalEntity"


class Document(TenantOwned):
    legal_entity = models.ForeignKey(LEGAL_ENTITY, on_delete=models.PROTECT, related_name="+")
    filename = models.CharField(max_length=200)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    storage_key = models.CharField(max_length=300)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "documents_document"
        constraints = [
            models.UniqueConstraint(fields=["legal_entity", "sha256"], name="documents_once"),
        ]


class DocumentLink(TenantOwned):
    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name="links")
    entry = models.ForeignKey(
        "ledger.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    line = models.ForeignKey(
        "ledger.JournalLine", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "documents_link"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(entry__isnull=False, line__isnull=True)
                    | models.Q(entry__isnull=True, line__isnull=False)
                ),
                name="documents_link_one_target",
            ),
            models.UniqueConstraint(
                fields=["document", "entry"], name="documents_link_entry_once",
                condition=models.Q(entry__isnull=False),
            ),
            models.UniqueConstraint(
                fields=["document", "line"], name="documents_link_line_once",
                condition=models.Q(line__isnull=False),
            ),
        ]  # fmt: skip
