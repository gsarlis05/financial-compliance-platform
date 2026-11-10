"""Workspace export and deletion (M5-6, doc 11 §9; M5 brief §3).

**Export.** One ZIP with every row of the workspace: a JSON-lines file per table, the files of
its documents, the members' names, and a manifest with the row count and SHA-256 of each file.
Tables are found from the database catalogue (every table with a ``tenant_id`` column), so a new
module's tables are included without a change here. Rows are read inside the workspace's
row-level security context and filtered by workspace as well.

**Deletion.** An owner requests it, then confirms it with a recent sign-in and the workspace's
name. The purge runs after a grace period (``WORKSPACE_DELETION_GRACE_DAYS``); until then an
owner can cancel. The purge is a maintenance job with the schema-owner role: it deletes every
row of the workspace in one transaction, proves that none is left, and leaves a record with
IDs, dates and row counts only. Posted entries and the audit trail are immutable for users;
deleting the whole workspace is the one case where they go, and only this job can do it.

Other modules add what the database cannot see (document files) with ``on_export`` and
``on_purge``.
"""

import hashlib
import io
import json
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from fcp.core.db.rls import set_context
from fcp.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from fcp.modules.audit_log.api import record as audit

from .models import Membership, WorkspaceDeletion
from .services import WorkspaceContext

EXPORT, DELETE = "tenancy.workspace.export", "tenancy.workspace.delete"
FORMAT_VERSION = 1

# (archive path, content) pairs for files outside the database, e.g. document files.
type ExportFiles = Callable[[UUID], Iterator[tuple[str, bytes]]]
# Removes what is outside the database; returns {"deleted": n, "retained": n}.
type PurgeFiles = Callable[[UUID], dict[str, int]]

_export_hooks: list[ExportFiles] = []
_purge_hooks: list[PurgeFiles] = []


def on_export(hook: ExportFiles) -> None:
    _export_hooks.append(hook)


def on_purge(hook: PurgeFiles) -> None:
    _purge_hooks.append(hook)


def _own_admin(ctx: WorkspaceContext, permission: str) -> None:
    """Workspace-wide owners only; never a firm user acting through an engagement."""
    ctx.authorize(permission)
    if ctx.permitted_entity_ids(permission) is not None or ctx.engagement is not None:
        raise PermissionDeniedError("Only the workspace's own owners can do this.")


def tenant_tables() -> list[str]:
    """Every table that holds rows of workspaces, from the catalogue."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.table_name FROM information_schema.columns c "
            "JOIN information_schema.tables t USING (table_schema, table_name) "
            "WHERE c.table_schema = 'public' AND c.column_name = 'tenant_id' "
            "AND t.table_type = 'BASE TABLE' AND c.table_name <> 'tenancy_workspace_deletion' "
            "ORDER BY c.table_name"
        )
        return [row[0] for row in cursor.fetchall()]


def _quoted(table: str) -> str:
    return connection.ops.quote_name(table)


# --- export ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Export:
    filename: str
    content: bytes
    manifest: dict[str, Any]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _table_lines(table: str, tenant_id: UUID) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT row_to_json(t)::text FROM {_quoted(table)} t WHERE t.tenant_id = %s "  # noqa: S608
            "ORDER BY 1",
            [tenant_id],
        )
        return [row[0] for row in cursor.fetchall()]


@transaction.atomic
def export(ctx: WorkspaceContext) -> Export:
    """Everything the workspace holds, as one ZIP (see the module text)."""
    _own_admin(ctx, EXPORT)
    tenant = ctx.tenant
    now = timezone.now()
    buffer = io.BytesIO()
    tables: dict[str, dict[str, Any]] = {}
    files: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        workspace = json.dumps(
            {"id": str(tenant.id), "slug": tenant.slug, "name": tenant.name, "kind": tenant.kind,
             "status": tenant.status, "data_region": tenant.data_region,
             "created_at": tenant.created_at.isoformat()},
            sort_keys=True,
        )  # fmt: skip
        archive.writestr("workspace.json", workspace)
        for table in tenant_tables():
            lines = _table_lines(table, tenant.id)
            data = ("\n".join(lines) + ("\n" if lines else "")).encode()
            archive.writestr(f"tables/{table}.jsonl", data)
            tables[table] = {"rows": len(lines), "sha256": _digest(data)}
        members = Membership.objects.filter(tenant=tenant).select_related("user")
        people = "".join(
            json.dumps({"id": str(m.user.id), "email": m.user.email,
                        "display_name": m.user.display_name}, sort_keys=True) + "\n"
            for m in members.order_by("user__email")
        )  # fmt: skip
        archive.writestr("members.jsonl", people)
        for hook in _export_hooks:
            for path, content in hook(tenant.id):
                archive.writestr(path, content)
                files[path] = {"bytes": len(content), "sha256": _digest(content)}
        manifest: dict[str, Any] = {
            "format_version": FORMAT_VERSION,
            "exported_at": now.isoformat(),
            "exported_by": str(ctx.user.id),
            "workspace": {"id": str(tenant.id), "slug": tenant.slug, "sha256": _digest(
                workspace.encode())},
            "members": {"rows": members.count(), "sha256": _digest(people.encode())},
            "tables": tables,
            "files": files,
        }  # fmt: skip
        archive.writestr("manifest.json", json.dumps(manifest, indent=1, sort_keys=True))
    audit(
        tenant_id=tenant.id,
        actor_user_id=ctx.user.id,
        action="tenancy.workspace.exported",
        subject_type="tenant",
        subject_id=tenant.id,
        changes={"tables": len(tables), "rows": sum(t["rows"] for t in tables.values()),
                 "files": len(files)},
    )  # fmt: skip
    name = f"{tenant.slug}-export-{now:%Y%m%d-%H%M%S}.zip"
    return Export(name, buffer.getvalue(), manifest)


# --- deletion: request, confirm, cancel --------------------------------------------------------


def deletion(tenant_id: UUID) -> WorkspaceDeletion | None:
    """The open deletion of a workspace (requested or confirmed, not purged), if any."""
    return WorkspaceDeletion.objects.filter(
        tenant_id=tenant_id, cancelled_at__isnull=True, purged_at__isnull=True
    ).first()


def _audit(ctx: WorkspaceContext, action: str, row: WorkspaceDeletion) -> None:
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action=f"tenancy.workspace.{action}",
        subject_type="tenant",
        subject_id=ctx.tenant.id,
        changes={"deletion": str(row.id),
                 "purge_after": row.purge_after.isoformat() if row.purge_after else None},
    )  # fmt: skip


@transaction.atomic
def request_deletion(ctx: WorkspaceContext) -> WorkspaceDeletion:
    _own_admin(ctx, DELETE)
    if deletion(ctx.tenant.id) is not None:
        raise ConflictError("The deletion of this workspace was already requested.")
    row = WorkspaceDeletion.objects.create(
        tenant_id=ctx.tenant.id, tenant_kind=ctx.tenant.kind, requested_by_id=ctx.user.id
    )
    _audit(ctx, "deletion_requested", row)
    return row


@transaction.atomic
def confirm_deletion(ctx: WorkspaceContext, *, workspace_name: str) -> WorkspaceDeletion:
    """Confirm with the workspace's exact name. The caller has checked the recent sign-in."""
    _own_admin(ctx, DELETE)
    row = deletion(ctx.tenant.id)
    if row is None:
        raise NotFoundError("No deletion was requested for this workspace.")
    if row.confirmed_at is not None:
        raise ConflictError("The deletion is already confirmed.")
    if workspace_name.strip() != ctx.tenant.name:
        message = "Type the workspace's name exactly to confirm."
        raise ValidationFailedError(message, field_errors={"workspace_name": [message]})
    now = timezone.now()
    row.confirmed_by_id, row.confirmed_at = ctx.user.id, now
    row.purge_after = now + timedelta(days=settings.WORKSPACE_DELETION_GRACE_DAYS)
    row.save(update_fields=["confirmed_by_id", "confirmed_at", "purge_after"])
    _audit(ctx, "deletion_confirmed", row)
    return row


@transaction.atomic
def cancel_deletion(ctx: WorkspaceContext) -> None:
    _own_admin(ctx, DELETE)
    row = deletion(ctx.tenant.id)
    if row is None:
        raise NotFoundError("No deletion was requested for this workspace.")
    row.cancelled_at = timezone.now()
    row.save(update_fields=["cancelled_at"])
    _audit(ctx, "deletion_cancelled", row)


# --- purge (maintenance job, schema-owner role) ------------------------------------------------


def _delete_order(tables: list[str]) -> list[str]:
    """Children before parents for foreign keys that cannot be deferred."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT child.relname, parent.relname FROM pg_constraint k "
            "JOIN pg_class child ON child.oid = k.conrelid "
            "JOIN pg_class parent ON parent.oid = k.confrelid "
            "WHERE k.contype = 'f' AND NOT k.condeferrable AND k.conrelid <> k.confrelid"
        )
        needs = {(child, parent) for child, parent in cursor.fetchall()}
    left, ordered = set(tables), []
    while left:
        free = sorted(t for t in left if not any(p == t and c in left for c, p in needs))
        if not free:
            raise RuntimeError(f"Foreign keys form a cycle that cannot be deferred: {sorted(left)}")
        ordered += free
        left -= set(free)
    return ordered


def _count(table: str, column: str, tenant_id: UUID) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT count(*) FROM {_quoted(table)} WHERE {column} = %s",  # noqa: S608
            [tenant_id],
        )
        return int(cursor.fetchone()[0])


def purge(row: WorkspaceDeletion, *, force: bool = False) -> dict[str, int]:
    """Delete every row and file of the workspace. Needs the schema-owner database role, because
    it switches off the immutability triggers for the duration of its transaction."""
    if row.purged_at or row.cancelled_at or not row.confirmed_at or not row.purge_after:
        raise ConflictError("This deletion is not confirmed, or is already finished.")
    if row.purge_after > timezone.now() and not force:
        raise ConflictError("The grace period has not ended.")
    tenant_id = row.tenant_id
    files = {"deleted": 0, "retained": 0}
    for hook in _purge_hooks:
        for key, value in hook(tenant_id).items():
            files[key] = files.get(key, 0) + value
    with transaction.atomic():
        set_context(tenant_id=tenant_id)
        tables = _delete_order(tenant_tables())
        every = [*tables, "tenancy_tenant"]
        counts: dict[str, int] = {}
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
            for table in every:
                cursor.execute(f"ALTER TABLE {_quoted(table)} DISABLE TRIGGER USER")
            for table in tables:
                cursor.execute(
                    f"DELETE FROM {_quoted(table)} WHERE tenant_id = %s",  # noqa: S608
                    [tenant_id],
                )
                if cursor.rowcount:
                    counts[table] = cursor.rowcount
            cursor.execute("DELETE FROM tenancy_tenant WHERE id = %s", [tenant_id])
            counts["tenancy_tenant"] = cursor.rowcount
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            for table in every:
                cursor.execute(f"ALTER TABLE {_quoted(table)} ENABLE TRIGGER USER")
        left = {t: n for t in tables if (n := _count(t, "tenant_id", tenant_id))}
        if left or _count("tenancy_tenant", "id", tenant_id):
            raise RuntimeError(f"Rows are left after the purge: {left}")
        row.purged_at, row.purged_rows, row.purged_files = timezone.now(), counts, files
        row.save(update_fields=["purged_at", "purged_rows", "purged_files"])
    return counts


def due() -> list[WorkspaceDeletion]:
    """Confirmed deletions whose grace period has ended."""
    return list(
        WorkspaceDeletion.objects.filter(
            confirmed_at__isnull=False, cancelled_at__isnull=True, purged_at__isnull=True,
            purge_after__lte=timezone.now(),
        ).order_by("purge_after")
    )  # fmt: skip
