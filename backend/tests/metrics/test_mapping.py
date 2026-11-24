"""Financial taxonomy, account mapping and the mapping-completeness check (M2-6, AC-M2-6)."""

from collections.abc import Callable
from typing import Any

import pytest
from django.conf import settings
from django.db import DatabaseError, connection, transaction

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.metrics.models import AccountTaxonomyMap

from ..ledger.conftest import books, join
from ..ledger.test_entries import act

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books"]


@pytest.fixture
def mb(books: dict[str, Any]) -> dict[str, Any]:
    """Books without an approval step, so entries post directly."""
    books["client"].put_json(f"{books['base']}/ledger-settings", {"approval_policy": "NONE"})
    return books


def post(mb: dict[str, Any], *lines: tuple[str, str, str], day: str = "2026-03-15") -> None:
    acc = mb["accounts"]
    body = {"accounting_date": day, "description": "Entry",
            "lines": [{"account_id": acc[c]["id"], "debit": d, "credit": cr}
                      for c, d, cr in lines]}  # fmt: skip
    draft = mb["client"].post_json(f"{mb['base']}/journal-entries", body)
    assert draft.status_code == 201, draft.content
    assert act(mb, draft.json()["id"], "post").status_code == 200


def completeness(mb: dict[str, Any], as_of: str = "2026-12-31") -> dict[str, Any]:
    response = mb["client"].get(f"{mb['base']}/account-mapping/completeness?as_of={as_of}")
    assert response.status_code == 200, response.content
    result: dict[str, Any] = response.json()
    return result


def defaults(mb: dict[str, Any]) -> int:
    response = mb["client"].post_json(f"{mb['base']}/account-mapping/apply-defaults",
                                      {"template": "cy_business"})  # fmt: skip
    assert response.status_code == 200, response.content
    mapped: int = response.json()["mapped"]
    return mapped


def put_map(mb: dict[str, Any], code: str, line: str | None) -> Any:
    return mb["client"].put_json(
        f"{mb['base']}/account-mapping/{mb['accounts'][code]['id']}", {"line_code": line}
    )


def test_taxonomy_lists_versioned_lines_in_order(mb: dict[str, Any]) -> None:
    lines = mb["client"].get(f"{mb['base']}/taxonomy").json()
    assert len(lines) == 35
    assert [ln["order"] for ln in lines] == sorted(ln["order"] for ln in lines)
    by_code = {ln["code"]: ln for ln in lines}
    assert by_code["REV.SALES"]["statement"] == "PL"
    assert by_code["BS.CASH"]["account_types"] == ["ASSET"]
    assert by_code["FX.DIFF"]["account_types"] == ["EXPENSE", "INCOME"]


def test_defaults_map_every_template_account_except_suspense_and_are_idempotent(
    mb: dict[str, Any],
) -> None:
    assert defaults(mb) == 43
    assert defaults(mb) == 0
    rows = {r["account_code"]: r for r in mb["client"].get(
        f"{mb['base']}/account-mapping?as_of=2026-12-31").json()}  # fmt: skip
    assert rows["1300"]["line_code"] == "BS.CASH"
    assert rows["7020"]["line_code"] == "FX.DIFF"
    assert rows["9999"]["line_code"] is None
    set_context(tenant_id=mb["ws"]["id"])
    assert AuditEvent.objects.filter(action="metrics.mapping.defaults_applied").count() == 1


def test_unmapped_accounts_with_a_balance_block_statements(mb: dict[str, Any]) -> None:
    post(mb, ("6100", "100.00", "0"), ("1300", "0", "100.00"))
    before = completeness(mb)
    assert before["complete"] is False
    assert {r["account_code"] for r in before["unmapped_blocking"]} == {"1300", "6100"}
    defaults(mb)
    assert completeness(mb)["complete"] is True
    # Suspense has no mapping on purpose: a balance there blocks until it is cleared.
    post(mb, ("9999", "5.00", "0"), ("1300", "0", "5.00"), day="2026-04-01")
    blocked = completeness(mb)
    assert [r["account_code"] for r in blocked["unmapped_blocking"]] == ["9999"]
    assert blocked["unmapped_blocking"][0]["balance"] == "5.00"
    post(mb, ("1300", "5.00", "0"), ("9999", "0", "5.00"), day="2026-04-02")
    cleared = completeness(mb)
    assert cleared["complete"] is True
    assert [r["account_code"] for r in cleared["unmapped_warning"]] == ["9999"]
    # Completeness is evaluated at a date: before the suspense posting, nothing is blocking.
    assert completeness(mb, "2026-03-31")["complete"] is True


@pytest.mark.parametrize(
    ("code", "line", "status", "field"),
    [
        ("6100", "BS.CASH", 422, "line_code"),  # an expense on a balance-sheet line
        ("1300", "REV.SALES", 422, "line_code"),  # an asset on a P&L line
        ("1300", "NOPE", 422, "line_code"),
        ("11", "BS.CASH", 422, "account_id"),  # a heading
    ],
)
def test_mapping_validation(mb: dict[str, Any], code: str, line: str, status: int,
                            field: str) -> None:  # fmt: skip
    response = put_map(mb, code, line)
    assert response.status_code == status
    assert field in response.json()["errors"]


def test_unknown_account_is_404(mb: dict[str, Any]) -> None:
    response = mb["client"].put_json(
        f"{mb['base']}/account-mapping/01a1a1a1-0000-7000-8000-000000000000", {"line_code": None}
    )
    assert response.status_code == 404


def test_changes_supersede_and_keep_history(mb: dict[str, Any]) -> None:
    assert put_map(mb, "6900", "OPEX.OTHER").json()["line_code"] == "OPEX.OTHER"
    assert put_map(mb, "6900", "OPEX.OTHER").status_code == 200  # no change, no new version
    assert put_map(mb, "6900", "OPEX.MARKETING").json()["line_code"] == "OPEX.MARKETING"
    assert put_map(mb, "6900", None).json()["line_code"] is None
    history = mb["client"].get(
        f"{mb['base']}/account-mapping/{mb['accounts']['6900']['id']}/history").json()  # fmt: skip
    assert [h["line_code"] for h in history] == ["OPEX.OTHER", "OPEX.MARKETING"]
    assert all(h["superseded_at"] for h in history)
    set_context(tenant_id=mb["ws"]["id"])
    changes = [e.changes for e in AuditEvent.objects.filter(action="metrics.mapping.changed")
               .order_by("seq")]  # fmt: skip
    assert [(c["before"], c["after"]) for c in changes] == [
        (None, "OPEX.OTHER"),
        ("OPEX.OTHER", "OPEX.MARKETING"),
        ("OPEX.MARKETING", None),
    ]


def test_history_is_append_only_in_the_database(mb: dict[str, Any]) -> None:
    put_map(mb, "6900", "OPEX.OTHER")
    set_context(tenant_id=mb["ws"]["id"])
    row = AccountTaxonomyMap.objects.get(account_id=mb["accounts"]["6900"]["id"])

    def delete() -> None:
        with transaction.atomic():
            AccountTaxonomyMap.objects.filter(id=row.id).delete()

    def rewrite() -> None:
        with transaction.atomic():
            AccountTaxonomyMap.objects.filter(id=row.id).update(line_id="IFRS_SME_CY@1.0:OPEX.RENT")

    with pytest.raises(DatabaseError, match="history is kept"):
        delete()
    with pytest.raises(DatabaseError, match="append-only"):
        rewrite()


def test_mapping_cannot_point_at_another_entitys_account(
    mb: dict[str, Any], make_user: Make, make_workspace: Make, api_client: Make
) -> None:
    other = make_user("other@example.test")
    ws = make_workspace(other, name="Other")
    oc = api_client(other)
    oe = oc.get(f"/api/w/{ws['slug']}/entities").json()[0]
    accounts = oc.post_json(f"/api/w/{ws['slug']}/entities/{oe['id']}/accounts/apply-template",
                            {"template": "cy_business"}).json()  # fmt: skip
    foreign = next(a for a in accounts if a["code"] == "1300")
    # Through the API the foreign account simply does not exist here.
    response = mb["client"].put_json(f"{mb['base']}/account-mapping/{foreign['id']}",
                                     {"line_code": "BS.CASH"})  # fmt: skip
    assert response.status_code == 404

    def insert_directly() -> None:
        with transaction.atomic():
            set_context(tenant_id=mb["ws"]["id"])
            AccountTaxonomyMap.objects.create(
                tenant_id=mb["ws"]["id"], legal_entity_id=mb["entity"]["id"],
                account_id=foreign["id"], taxonomy_version_id="IFRS_SME_CY@1.0",
                line_id="IFRS_SME_CY@1.0:BS.CASH", created_by=mb["owner"],
            )  # fmt: skip

    with pytest.raises(DatabaseError):
        insert_directly()


def test_read_only_users_can_view_but_not_change_the_mapping(
    mb: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    viewer = join(mb["client"], mb["ws"]["slug"], make_user("ro@example.test"), api_client,
                  "read_only")  # fmt: skip
    assert viewer.get(f"{mb['base']}/account-mapping?as_of=2026-12-31").status_code == 200
    denied = viewer.put_json(f"{mb['base']}/account-mapping/{mb['accounts']['6100']['id']}",
                             {"line_code": "OPEX.RENT"})  # fmt: skip
    assert denied.status_code == 403


def test_taxonomy_tables_are_read_only_for_the_runtime_role() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
            "WHERE table_name LIKE 'metrics_taxonomy_%%' AND grantee = %s",
            [settings.DB_APP_ROLE_NAME],
        )
        grants = cursor.fetchall()
    assert sorted(grants) == [("metrics_taxonomy_line", "SELECT"),
                              ("metrics_taxonomy_version", "SELECT")]  # fmt: skip


def test_defaults_need_a_known_template(mb: dict[str, Any]) -> None:
    response = mb["client"].post_json(
        f"{mb['base']}/account-mapping/apply-defaults", {"template": "personal"}
    )
    assert response.status_code == 422
    assert response.json()["errors"]["template"] == ["unknown"]
