"""The firm portfolio (M4-9, AC-DB6): only the client entities the user may see, computed on each
request under the user's permissions, so a revoked client disappears at once and nothing derived
from it is kept."""

from collections.abc import Callable
from typing import Any

import pytest
from django.db import connection

from fcp.modules.tenancy.api import Role

from ..ledger.conftest import join

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]


@pytest.fixture
def firm(make_user: Make, api_client: Make, make_workspace: Make) -> dict[str, Any]:
    owner = make_user("partner@example.test")
    ws = make_workspace(owner, kind="FIRM", name="Firm")
    oc = api_client(owner)
    made = {}
    for name in ("Client A", "Client B"):
        created = oc.post_json(f"/api/w/{ws['slug']}/entities",
                               {"legal_name": name, "entity_type": "COMPANY"})  # fmt: skip
        assert created.status_code == 201, created.content
        made[name] = created.json()
    return {"ws": ws, "oc": oc, "a": made["Client A"], "b": made["Client B"]}


def names(client: Any, slug: str) -> list[str]:
    got = client.get(f"/api/w/{slug}/portfolio?month=2026-10-01")
    assert got.status_code == 200, got.content
    return [r["legal_name"] for r in got.json()]


def test_only_granted_clients_and_revocation_is_immediate(
    firm: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    slug = firm["ws"]["slug"]
    assert {"Client A", "Client B"} <= set(names(firm["oc"], slug))
    staff = make_user("staff@example.test")
    client = join(firm["oc"], slug, staff, api_client, Role.ACCOUNTANT, firm["a"]["id"])
    assert names(client, slug) == ["Client A"]

    members = firm["oc"].get(f"/api/w/{slug}/members").json()
    target = next(m for m in members if m["email"] == staff.email)
    granted = firm["oc"].post_json(f"/api/w/{slug}/members/{target['membership_id']}/roles",
                                   {"role_key": Role.ACCOUNTANT,
                                    "legal_entity_id": firm["b"]["id"]})  # fmt: skip
    assert granted.status_code == 201, granted.content
    assert names(client, slug) == ["Client A", "Client B"]
    row = next(r for r in client.get(f"/api/w/{slug}/portfolio?month=2026-10-01").json()
               if r["legal_name"] == "Client B")  # fmt: skip
    assert row["cash"] == {"status": "empty", "reason": "No cash forecast yet: run one first.",
                           "data": {}}  # fmt: skip
    assert row["goals"]["data"] == {"ON_TRACK": 0, "AT_RISK": 0, "OFF_TRACK": 0,
                                    "UNDETERMINED": 0, "NOT_EVALUATED": 0}  # fmt: skip
    assert row["alerts"]["data"] == {"warning": 0, "critical": 0}
    assert row["kpis"]["status"] == "empty"

    revoked = firm["oc"].delete_json(f"/api/w/{slug}/roles/{granted.json()['id']}")
    assert revoked.status_code == 204
    assert names(client, slug) == ["Client A"]  # gone on the next request
    # Nothing derived from the portfolio is stored: there is no table to purge.
    assert "portfolio" not in " ".join(connection.introspection.table_names())


def test_a_user_without_planning_access_is_refused(
    firm: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    slug = firm["ws"]["slug"]
    holder = join(firm["oc"], slug, make_user("bh@example.test"), api_client,
                  Role.BUDGET_HOLDER, firm["a"]["id"])  # fmt: skip
    assert holder.get(f"/api/w/{slug}/portfolio?month=2026-10-01").status_code == 403
