"""Audit trail: completeness, append-only, tamper detection (doc 09 AC-D1, D2, D3)."""

import threading
from collections.abc import Callable
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, connections, transaction

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.api import record, verify
from fcp.modules.audit_log.models import AuditChainHead, AuditEvent
from fcp.modules.identity.models import User
from fcp.modules.tenancy import services
from fcp.modules.tenancy.api import all_tenant_ids

Make = Callable[..., Any]


def events(tenant_id: Any) -> list[AuditEvent]:
    set_context(tenant_id=tenant_id)
    return list(AuditEvent.objects.filter(tenant_id=tenant_id).order_by("seq"))


def execute(sql: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql)


@pytest.fixture
def workspace(make_user: Make) -> services.WorkspaceContext:
    return services.create_workspace(
        make_user("owner@example.test"), name="Audit Co", kind="BUSINESS", entity_name="A Ltd"
    )


# --- AC-D1: every change is audited in the same transaction --------------------------------------


@pytest.mark.django_db
def test_workspace_creation_is_audited(workspace: services.WorkspaceContext) -> None:
    actions = [e.action for e in events(workspace.tenant.id)]
    assert actions == [
        "tenancy.workspace.created",
        "tenancy.role.granted",
        "tenancy.entity.created",
    ]
    first = events(workspace.tenant.id)[0]
    assert first.actor_user_id == workspace.user.id
    assert first.actor_type == "USER"
    assert first.changes == {"kind": "BUSINESS", "name": "Audit Co"}
    assert verify(workspace.tenant.id).ok


@pytest.mark.django_db
def test_invitation_role_and_entity_changes_are_audited(
    workspace: services.WorkspaceContext, make_user: Make
) -> None:
    invitee = make_user("invitee@example.test")
    issued = services.invite_member(workspace, email=invitee.email, role_key="accountant")
    services.accept_invitation(invitee, issued.token)
    ctx = services.enter_workspace(workspace.user, workspace.tenant.slug)
    services.create_entity(ctx, legal_name="B Ltd", entity_type="COMPANY")
    actions = [e.action for e in events(workspace.tenant.id)][3:]
    assert actions == [
        "tenancy.invitation.created",
        "tenancy.invitation.accepted",
        "tenancy.role.granted",
        "tenancy.entity.created",
    ]
    assert verify(workspace.tenant.id).ok


@pytest.mark.django_db
def test_rolled_back_change_leaves_no_audit_event(workspace: services.WorkspaceContext) -> None:
    before = len(events(workspace.tenant.id))

    def change_then_fail() -> None:
        with transaction.atomic():
            services.create_entity(workspace, legal_name="Doomed Ltd", entity_type="COMPANY")
            raise RuntimeError("simulated failure after the change")

    with pytest.raises(RuntimeError):
        change_then_fail()
    assert len(events(workspace.tenant.id)) == before
    assert verify(workspace.tenant.id).ok


@pytest.mark.django_db
def test_record_requires_a_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    class NotInTransaction:
        in_atomic_block = False

    monkeypatch.setattr("fcp.modules.audit_log.chain.connection", NotInTransaction())
    with pytest.raises(RuntimeError, match="inside the transaction"):
        record(tenant_id=None, action="x", subject_type="x", subject_id="x", actor_user_id=None)  # type: ignore[arg-type]


# --- AC-D3: no secrets or personal data in events ----------------------------------------------


@pytest.mark.django_db
def test_sensitive_values_are_stored_as_digests(workspace: services.WorkspaceContext) -> None:
    services.invite_member(workspace, email="Secret.Person@Example.test", role_key="read_only")
    invitation = next(
        e for e in events(workspace.tenant.id) if e.action == "tenancy.invitation.created"
    )
    assert invitation.changes["email"].startswith("sha256:")
    assert "secret.person" not in str(invitation.changes).lower()
    assert "token" not in invitation.changes


# --- append-only ---------------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_log_event SET action = 'forged'",
        "DELETE FROM audit_log_event",
        "TRUNCATE audit_log_event",
    ],
)
def test_trigger_blocks_changes_even_for_the_owner(
    workspace: services.WorkspaceContext, statement: str
) -> None:
    set_context(tenant_id=workspace.tenant.id)
    with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():  # noqa: PT012
        execute("SET LOCAL fcp.allow_audit_truncate = 'off'")  # as in production
        execute(statement)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "statement", ["UPDATE audit_log_event SET action = 'forged'", "DELETE FROM audit_log_event"]
)
def test_runtime_role_has_no_update_or_delete_privilege(
    workspace: services.WorkspaceContext, statement: str
) -> None:
    with transaction.atomic():
        execute("SET LOCAL ROLE fcp_app")
        set_context(tenant_id=workspace.tenant.id)
        assert AuditEvent.objects.count() == 3  # reading is allowed
        with pytest.raises(DatabaseError, match="permission denied"), transaction.atomic():
            execute(statement)


# --- AC-D2: tampering is detected ----------------------------------------------------------------


def _tamper(sql: str) -> None:
    """Simulate an attacker with DDL rights who disables the protection trigger."""
    execute("ALTER TABLE audit_log_event DISABLE TRIGGER audit_log_event_append_only")
    try:
        execute(sql)
    finally:
        execute("ALTER TABLE audit_log_event ENABLE TRIGGER audit_log_event_append_only")


@pytest.mark.django_db
def test_altered_event_content_is_detected(workspace: services.WorkspaceContext) -> None:
    set_context(tenant_id=workspace.tenant.id)
    forged = '{"name": "Other Co", "kind": "BUSINESS"}'
    _tamper(f"UPDATE audit_log_event SET changes = '{forged}' WHERE seq = 1")  # noqa: S608
    status = verify(workspace.tenant.id)
    assert not status.ok
    assert status.broken_at_seq == 1
    assert status.reason == "event content altered"


@pytest.mark.django_db
def test_deleted_event_is_detected(workspace: services.WorkspaceContext) -> None:
    set_context(tenant_id=workspace.tenant.id)
    _tamper("DELETE FROM audit_log_event WHERE seq = 2")
    status = verify(workspace.tenant.id)
    assert not status.ok
    assert status.broken_at_seq == 3
    assert "gap" in status.reason


@pytest.mark.django_db
def test_truncated_tail_is_detected_by_the_chain_head(workspace: services.WorkspaceContext) -> None:
    set_context(tenant_id=workspace.tenant.id)
    _tamper("DELETE FROM audit_log_event WHERE seq = 3")
    status = verify(workspace.tenant.id)
    assert not status.ok
    assert status.reason == "chain head does not match events"


@pytest.mark.django_db
def test_rewritten_chain_head_is_detected(workspace: services.WorkspaceContext) -> None:
    set_context(tenant_id=workspace.tenant.id)
    AuditChainHead.objects.filter(tenant_id=workspace.tenant.id).update(last_seq=99)
    assert not verify(workspace.tenant.id).ok


# --- concurrency -------------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_appends_are_gapless(make_user: Make) -> None:
    ctx = services.create_workspace(make_user(), name="Busy", kind="PERSONAL")
    tenant_id, user_id = ctx.tenant.id, ctx.user.id
    errors: list[BaseException] = []

    def append(n: int) -> None:
        try:
            with transaction.atomic():
                set_context(tenant_id=tenant_id, user_id=user_id)
                record(tenant_id=tenant_id, action="test.concurrent", subject_type="probe",
                       subject_id=n, actor_user_id=user_id)  # fmt: skip
        except BaseException as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=append, args=(n,)) for n in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    with transaction.atomic():
        seqs = [e.seq for e in events(tenant_id)]
        assert seqs == list(range(1, len(seqs) + 1))
        assert len(seqs) == 3 + 20
        assert verify(tenant_id).ok


# --- verification command and API --------------------------------------------------------------


@pytest.mark.django_db
def test_verify_command_checks_every_workspace(
    workspace: services.WorkspaceContext, make_user: Make, capsys: pytest.CaptureFixture[str]
) -> None:
    services.create_workspace(make_user(), name="Second", kind="PERSONAL")
    assert len(all_tenant_ids()) == 2
    call_command("audit_verify")
    assert "Verified 2 workspace(s); 0 broken." in capsys.readouterr().out
    set_context(tenant_id=workspace.tenant.id)
    _tamper("UPDATE audit_log_event SET action = 'forged' WHERE seq = 1")
    with pytest.raises(CommandError, match="1 audit chain"):
        call_command("audit_verify")


@pytest.mark.django_db
def test_audit_api_lists_and_verifies(
    make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    owner = make_user()
    ws = make_workspace(owner)
    client = api_client(owner)
    listed = client.get(f"/api/w/{ws['slug']}/audit-events").json()
    assert [e["seq"] for e in listed] == [1, 2, 3]
    assert len(listed[0]["hash"]) == 64
    filtered = client.get(
        f"/api/w/{ws['slug']}/audit-events", {"subject_type": "legal_entity"}
    ).json()
    assert [e["action"] for e in filtered] == ["tenancy.entity.created"]
    assert client.get(f"/api/w/{ws['slug']}/audit-events/verify").json() == {
        "ok": True, "events": 3, "broken_at_seq": None, "reason": "",
    }  # fmt: skip


@pytest.mark.django_db
def test_audit_api_requires_audit_permission(
    make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    owner, viewer = make_user(), make_user("viewer@example.test")
    ws = make_workspace(owner)
    token = (
        api_client(owner)
        .post_json(
            f"/api/w/{ws['slug']}/invitations", {"email": viewer.email, "role_key": "read_only"}
        )
        .json()["token"]
    )
    viewer_client = api_client(viewer)
    viewer_client.post_json("/api/invitations/accept", {"token": token})
    assert viewer_client.get(f"/api/w/{ws['slug']}/audit-events").status_code == 403


@pytest.mark.django_db
def test_audit_events_are_isolated_between_tenants(
    workspace: services.WorkspaceContext, make_user: Make
) -> None:
    other = services.create_workspace(make_user(), name="Other", kind="PERSONAL")
    set_context(tenant_id=workspace.tenant.id)
    assert set(AuditEvent.objects.values_list("tenant_id", flat=True)) == {workspace.tenant.id}
    set_context(tenant_id=other.tenant.id)
    assert set(AuditEvent.objects.values_list("tenant_id", flat=True)) == {other.tenant.id}


def test_user_model_is_available() -> None:
    assert User.__name__ == "User"
