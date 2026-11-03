"""Ledger fixtures: a business workspace with an entity, its chart of accounts and FY2026."""

from collections.abc import Callable
from typing import Any

import pytest

Make = Callable[..., Any]


def join(owner_client: Any, slug: str, user: Any, client_factory: Make, role: str,
         entity_id: str | None = None) -> Any:  # fmt: skip
    body: dict[str, Any] = {"email": user.email, "role_key": role}
    if entity_id:
        body["legal_entity_id"] = entity_id
    issued = owner_client.post_json(f"/api/w/{slug}/invitations", body)
    assert issued.status_code == 201, issued.content
    client = client_factory(user)
    accepted = client.post_json("/api/invitations/accept", {"token": issued.json()["token"]})
    assert accepted.status_code == 200
    return client


@pytest.fixture
def books(make_user: Make, api_client: Make, make_workspace: Make) -> dict[str, Any]:
    owner = make_user("owner@example.test")
    ws = make_workspace(owner, name="Demo Trading")
    client = api_client(owner)
    entity = client.get(f"/api/w/{ws['slug']}/entities").json()[0]
    base = f"/api/w/{ws['slug']}/entities/{entity['id']}"
    applied = client.post_json(f"{base}/accounts/apply-template", {"template": "cy_business"})
    assert applied.status_code == 201, applied.content
    fy = client.post_json(f"{base}/fiscal-years", {"start_date": "2026-01-01"})
    assert fy.status_code == 201, fy.content
    accounts = {a["code"]: a for a in applied.json()}
    return {"owner": owner, "ws": ws, "client": client, "entity": entity, "base": base,
            "accounts": accounts, "fy": fy.json()}  # fmt: skip
