from collections.abc import Iterator
from uuid import UUID

from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    name = "fcp.modules.documents"
    label = "documents"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        """Document files are part of a workspace's export and of its purge (M5-6)."""
        from fcp.modules.tenancy.api import on_workspace_export, on_workspace_purge  # noqa: PLC0415

        from . import storage  # noqa: PLC0415
        from .models import Document  # noqa: PLC0415

        def files(tenant_id: UUID) -> Iterator[tuple[str, bytes]]:
            for doc in Document.objects.filter(tenant_id=tenant_id).order_by("id"):
                yield f"documents/{doc.id}/{doc.filename}", storage.get(tenant_id, doc.storage_key)

        on_workspace_export(files)
        on_workspace_purge(storage.delete_all)
