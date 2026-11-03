"""Database-level tenant isolation (doc 09 AC-B4, AC-B5; doc 04 §5)."""

from collections.abc import Callable

import pytest
from django.db import DatabaseError, connection, transaction

from fcp.core.db.registry import GLOBAL_TABLES
from fcp.core.db.rls import RlsContextError, set_context
from fcp.modules.identity.models import User
from fcp.modules.tenancy import services
from fcp.modules.tenancy.models import LegalEntity, Membership, RoleAssignment, Tenant

pytestmark = pytest.mark.django_db(transaction=False)


def scalar(sql: str, params: list[object] | None = None) -> object:
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        row = cursor.fetchone()
    return row[0] if row else None


def tables() -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
        return [r[0] for r in cursor.fetchall()]


def has_tenant_column(table: str) -> bool:
    return bool(
        scalar(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' "
            "AND table_name = %s AND column_name = 'tenant_id'",
            [table],
        )
    )


# --- AC-B5: schema check -------------------------------------------------------------------------


def test_every_table_is_classified_and_tenant_tables_force_rls() -> None:
    problems = []
    for table in tables():
        rls_forced = scalar(
            "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
            "WHERE oid = %s::regclass",
            [f"public.{table}"],
        )
        policies = scalar("SELECT count(*) FROM pg_policies WHERE tablename = %s", [table])
        if has_tenant_column(table) or table == "tenancy_tenant":
            if not rls_forced or not policies:
                problems.append(f"{table}: tenant table without FORCE RLS and a policy")
        elif table not in GLOBAL_TABLES:
            problems.append(f"{table}: not classified (add tenant_id + RLS, or GLOBAL_TABLES)")
    assert problems == [], "\n".join(problems)


def test_connection_role_cannot_bypass_rls() -> None:
    row = scalar(
        "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
    )
    assert row is False


# --- AC-B4: no context, no rows; no writes into another tenant ---------------------------------


@pytest.fixture
def two_workspaces(make_user: Callable[..., User]) -> tuple[services.WorkspaceContext, ...]:
    alice, bob = make_user("alice@example.test"), make_user("bob@example.test")
    a = services.create_workspace(alice, name="Alice Co", kind="BUSINESS", entity_name="A Ltd")
    b = services.create_workspace(bob, name="Bob Co", kind="BUSINESS", entity_name="B Ltd")
    return a, b


def test_without_context_every_tenant_table_is_empty(
    two_workspaces: tuple[services.WorkspaceContext, ...],
) -> None:
    set_context(tenant_id=None, user_id=None)
    for table in tables():
        if has_tenant_column(table) or table == "tenancy_tenant":
            assert scalar(f'SELECT count(*) FROM "{table}"') == 0, table


def test_context_shows_only_own_tenant(two_workspaces: tuple[services.WorkspaceContext, ...]) -> None:
    a, b = two_workspaces
    set_context(tenant_id=a.tenant.id, user_id=a.user.id)
    assert list(LegalEntity.objects.values_list("tenant_id", flat=True)) == [a.tenant.id]
    assert list(Tenant.objects.values_list("id", flat=True)) == [a.tenant.id]
    assert not LegalEntity.objects.filter(tenant_id=b.tenant.id).exists()


def test_insert_with_foreign_tenant_id_is_rejected(
    two_workspaces: tuple[services.WorkspaceContext, ...],
) -> None:
    a, b = two_workspaces
    set_context(tenant_id=a.tenant.id, user_id=a.user.id)
    with pytest.raises(DatabaseError, match="row-level security"), transaction.atomic():
        LegalEntity.objects.create(
            tenant_id=b.tenant.id, legal_name="Intruder", entity_type="COMPANY", created_by=a.user
        )


def test_update_cannot_move_a_row_to_another_tenant(
    two_workspaces: tuple[services.WorkspaceContext, ...],
) -> None:
    a, b = two_workspaces
    set_context(tenant_id=a.tenant.id, user_id=a.user.id)
    with pytest.raises(DatabaseError, match="row-level security"), transaction.atomic():
        LegalEntity.objects.filter(tenant_id=a.tenant.id).update(tenant_id=b.tenant.id)


def test_composite_fk_blocks_cross_tenant_references(
    two_workspaces: tuple[services.WorkspaceContext, ...],
) -> None:
    a, b = two_workspaces
    set_context(tenant_id=b.tenant.id, user_id=b.user.id)
    b_membership_id = Membership.objects.get().id
    set_context(tenant_id=a.tenant.id, user_id=a.user.id)
    with pytest.raises(DatabaseError, match="tenant_fk"), transaction.atomic():
        RoleAssignment.objects.create(
            tenant_id=a.tenant.id, membership_id=b_membership_id, role_key="read_only",
            granted_by=a.user,
        )  # fmt: skip


def test_runtime_role_cannot_disable_rls_or_change_schema(
    two_workspaces: tuple[services.WorkspaceContext, ...],
) -> None:
    a, _ = two_workspaces
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE fcp_app")
        set_context(tenant_id=a.tenant.id, user_id=a.user.id)
        assert LegalEntity.objects.count() == 1  # data access works
        for statement in (
            "ALTER TABLE tenancy_legal_entity DISABLE ROW LEVEL SECURITY",
            "ALTER TABLE tenancy_legal_entity NO FORCE ROW LEVEL SECURITY",
            "DROP POLICY tenant_isolation ON tenancy_legal_entity",
            "CREATE TABLE sneaky (id int)",
        ):
            with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as c:
                c.execute(statement)


def test_set_context_outside_a_transaction_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class NotInTransaction:
        in_atomic_block = False

    monkeypatch.setattr("fcp.core.db.rls.connection", NotInTransaction())
    with pytest.raises(RlsContextError):
        set_context(tenant_id=None)
