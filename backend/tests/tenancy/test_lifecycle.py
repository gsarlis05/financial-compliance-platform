"""Workspace export and deletion (M5-6): the export holds every row (counts and hashes); a
deleted workspace leaves no rows behind after the purge, and other workspaces are untouched."""

import hashlib
import io
import json
import zipfile
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from fcp.core.db.rls import set_context
from fcp.core.errors import ConflictError
from fcp.modules.audit_log.api import verify as verify_chain
from fcp.modules.documents import storage
from fcp.modules.tenancy import lifecycle
from fcp.modules.tenancy.models import WorkspaceDeletion

from ..ledger.conftest import books, join
from ..ledger.test_closing import no_approval, post

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books"]

PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"


def settle(tenant_id: str) -> None:
    """Run the deferred checks now, in the workspace that wrote (one request commits at a time
    in production; here the whole test is one transaction)."""
    set_context(tenant_id=UUID(tenant_id))
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")


def counts(tenant_id: str) -> dict[str, int]:
    set_context(tenant_id=UUID(tenant_id))
    found = {}
    with connection.cursor() as cursor:
        for table in lifecycle.tenant_tables():
            cursor.execute(
                f'SELECT count(*) FROM "{table}" WHERE tenant_id = %s',  # noqa: S608
                [tenant_id],
            )
            found[table] = cursor.fetchone()[0]
    return found


@pytest.fixture
def world(books: dict[str, Any], make_user: Make, api_client: Make, make_workspace: Make,
          document_bucket: None) -> dict[str, Any]:  # fmt: skip
    """A business with a posted entry and a document, and another workspace next to it."""
    del document_bucket
    no_approval(books)
    post(books, ("6100", "100.00", "0.00"), ("1300", "0.00", "100.00"))
    c = books["client"]
    up = c.post(f"{books['base']}/documents", {"file": SimpleUploadedFile("invoice.pdf", PDF)},
                headers=c._csrf())  # fmt: skip
    assert up.status_code == 201, up.content
    settle(books["ws"]["id"])
    other_owner = make_user("other@example.test")
    other = make_workspace(other_owner, name="Other Co")
    return {"books": books, "c": c, "slug": books["ws"]["slug"], "id": books["ws"]["id"],
            "doc": up.json(), "other": other, "oc": api_client(other_owner)}  # fmt: skip


def test_export_holds_every_row_with_counts_and_hashes(world: dict[str, Any], make_user: Make,
                                                       api_client: Make) -> None:  # fmt: skip
    w, c = world, world["c"]
    before = counts(w["id"])
    made = c.post_json(f"/api/w/{w['slug']}/export", {})
    assert made.status_code == 200, made.content
    assert made["Content-Type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(made.content))
    manifest = json.loads(archive.read("manifest.json"))

    # Every table of the workspace, with the same row count as the database had.
    assert {t: m["rows"] for t, m in manifest["tables"].items()} == before
    assert before["ledger_journal_line"] == 2 and before["documents_document"] == 1  # noqa: PT018
    for table, meta in manifest["tables"].items():
        data = archive.read(f"tables/{table}.jsonl")
        assert hashlib.sha256(data).hexdigest() == meta["sha256"], table
        rows = [json.loads(line) for line in data.splitlines()]
        assert len(rows) == meta["rows"], table
        assert all(row["tenant_id"] == w["id"] for row in rows), table

    # The document file itself, byte for byte.
    path = f"documents/{w['doc']['id']}/invoice.pdf"
    assert archive.read(path) == PDF
    assert manifest["files"][path] == {"bytes": len(PDF), "sha256": hashlib.sha256(PDF).hexdigest()}
    assert json.loads(archive.read("workspace.json"))["slug"] == w["slug"]
    assert "owner@example.test" in archive.read("members.jsonl").decode()

    # Nothing of another workspace.
    everything = b"".join(archive.read(name) for name in archive.namelist())
    assert w["other"]["id"].encode() not in everything
    assert b"other@example.test" not in everything

    # Owners only: not an accountant of the workspace, not the owner of another one.
    accountant = join(c, w["slug"], make_user("acc@example.test"), api_client, "accountant")
    assert accountant.post_json(f"/api/w/{w['slug']}/export", {}).status_code == 403
    assert w["oc"].post_json(f"/api/w/{w['slug']}/export", {}).status_code == 404
    set_context(tenant_id=UUID(w["id"]))
    assert verify_chain(UUID(w["id"])).ok  # the export itself is in the audit trail


def test_deletion_is_requested_confirmed_and_purged_after_the_grace_period(  # noqa: PLR0915
    world: dict[str, Any],  # one story, start to finish, reads best as one test
) -> None:
    w, c = world, world["c"]
    url = f"/api/w/{w['slug']}/deletion"
    assert c.get(url).json()["status"] == "NONE"
    assert c.post_json(f"{url}/confirm", {"workspace_name": "Demo Trading"}).status_code == 404
    assert c.post_json(url, {}).json()["status"] == "REQUESTED"
    assert c.post_json(url, {}).status_code == 409
    assert w["oc"].post_json(url, {}).status_code == 404  # not their workspace

    # Nothing is due before the owner confirms with the exact name.
    assert lifecycle.due() == []
    assert c.post_json(f"{url}/confirm", {"workspace_name": "demo trading"}).status_code == 422
    confirmed = c.post_json(f"{url}/confirm", {"workspace_name": "Demo Trading"})
    assert confirmed.status_code == 200, confirmed.content
    body = confirmed.json()
    assert (body["status"], body["grace_days"]) == ("CONFIRMED", 30)
    assert c.get(f"/api/w/{w['slug']}").json()["deletion_due"] == body["purge_after"]

    # The grace period: still usable, cancellable, and not purged early.
    row = WorkspaceDeletion.objects.get(workspace_id=w["id"], cancelled_at__isnull=True)
    assert row.purge_after is not None
    assert timedelta(days=29) < row.purge_after - timezone.now() <= timedelta(days=30)
    assert lifecycle.due() == []
    with pytest.raises(ConflictError):
        lifecycle.purge(row)
    assert c.post_json(f"{url}/cancel", {}).json()["status"] == "NONE"
    assert c.get(f"/api/w/{w['slug']}").json()["deletion_due"] is None

    # Requested and confirmed again; the grace period ends.
    c.post_json(url, {})
    c.post_json(f"{url}/confirm", {"workspace_name": "Demo Trading"})
    settle(w["id"])
    row = WorkspaceDeletion.objects.get(workspace_id=w["id"], cancelled_at__isnull=True)
    WorkspaceDeletion.objects.filter(id=row.id).update(purge_after=timezone.now())
    other_before = counts(w["other"]["id"])
    had = counts(w["id"])
    assert storage.get(UUID(w["id"]), storage.document_key(UUID(w["id"]), UUID(w["doc"]["id"])))

    due = lifecycle.due()
    assert [d.id for d in due] == [row.id]
    purged = lifecycle.purge(due[0])

    # No row of the workspace is left in any table, and the workspace is gone.
    assert all(n == 0 for n in counts(w["id"]).values())
    assert purged["ledger_journal_line"] == had["ledger_journal_line"] == 2
    assert purged["tenancy_tenant"] == 1
    assert c.get(f"/api/w/{w['slug']}").status_code == 404
    assert [x["name"] for x in c.get("/api/workspaces").json()] == []
    with pytest.raises(storage.StorageUnavailableError):
        storage.get(UUID(w["id"]), storage.document_key(UUID(w["id"]), UUID(w["doc"]["id"])))

    # The record that remains holds IDs, dates and counts only.
    row.refresh_from_db()
    assert row.purged_at is not None
    assert row.purged_files == {"deleted": 1, "retained": 0}
    assert sum(row.purged_rows.values()) == sum(had.values()) + 1
    assert lifecycle.due() == []

    # The other workspace is untouched, its audit chain is intact, and the guards are back on.
    assert counts(w["other"]["id"]) == other_before
    set_context(tenant_id=UUID(w["other"]["id"]))
    assert verify_chain(UUID(w["other"]["id"])).ok
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgenabled = 'D'")
        assert cursor.fetchone()[0] == 0


def test_the_purge_job_runs_only_what_is_due(world: dict[str, Any]) -> None:
    w, c = world, world["c"]
    out = io.StringIO()
    call_command("tenancy_purge_workspaces", stdout=out)
    assert "0 workspace(s) purged; 0 failed." in out.getvalue()

    url = f"/api/w/{w['slug']}/deletion"
    c.post_json(url, {})
    c.post_json(f"{url}/confirm", {"workspace_name": "Demo Trading"})
    settle(w["id"])
    call_command("tenancy_purge_workspaces", stdout=out)  # inside the grace period: nothing
    assert c.get(f"/api/w/{w['slug']}").status_code == 200
    WorkspaceDeletion.objects.filter(workspace_id=w["id"]).update(purge_after=timezone.now())
    call_command("tenancy_purge_workspaces", stdout=out)
    assert "1 workspace(s) purged; 0 failed." in out.getvalue()
    assert c.get(f"/api/w/{w['slug']}").status_code == 404

    with override_settings(DB_ROLE="app"), pytest.raises(CommandError, match="DB_ROLE=owner"):
        call_command("tenancy_purge_workspaces")


def test_a_partner_can_export_but_only_an_owner_can_delete(
    make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    owner = make_user("founder@firm.test")
    firm = make_workspace(owner, kind="FIRM", name="Sarlis & Co")
    partner = join(api_client(owner), firm["slug"], make_user("partner@firm.test"), api_client,
                   "partner")  # fmt: skip
    assert partner.post_json(f"/api/w/{firm['slug']}/export", {}).status_code == 200
    refused = partner.post_json(f"/api/w/{firm['slug']}/deletion", {})
    assert refused.status_code == 403, refused.content
    assert refused.json()["detail"] == "Only an owner of the workspace can delete it."
    assert api_client(owner).post_json(f"/api/w/{firm['slug']}/deletion", {}).status_code == 201
