"""Alert emails (M8-5, AC-EM1): off by default; at most one immediate email per alert and user;
a daily digest; only for users who may see the alert; titles and links but no amounts; a working
one-click unsubscribe; retries, then failure recorded; an hourly limit."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from django.core import mail
from django.test import Client, override_settings

from fcp.core.db.rls import set_context
from fcp.modules.dashboards import emails
from fcp.modules.dashboards.models import AlertEmail, AlertEmailPreference

from ..goals.test_goals import budget, evaluate, g, goal
from ..kpi.test_kpis import k
from ..ledger.conftest import books, join

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books", "g", "k"]
URL = "/api/w/{slug}/alert-email-preference"


def prefer(g: dict[str, Any], mode: str, client: Any = None, language: str = "en") -> Any:
    got = (client or g["client"]).put_json(URL.format(slug=g["ws"]["slug"]),
                                           {"mode": mode, "language": language})  # fmt: skip
    assert got.status_code == 200, got.content
    return got.json()


def off_track(g: dict[str, Any], name: str = "Revenue 12k") -> None:
    """A goal evaluated as off track raises one alert (M4-7)."""
    made = goal(g, name, "REVENUE", "ABSOLUTE", "12000")
    evaluate(g, made["id"])


def send(g: dict[str, Any], now: datetime | None = None) -> emails.SendReport:
    return emails.send_all(now, tenants=lambda: [UUID(g["ws"]["id"])])


def test_immediate_email_once_with_titles_only(g: dict[str, Any], make_user: Make,
                                               api_client: Make) -> None:  # fmt: skip
    budget(g)
    assert g["client"].get(URL.format(slug=g["ws"]["slug"])).json() == {
        "mode": "OFF",
        "language": "en",
    }
    quiet = join(g["client"], g["ws"]["slug"], make_user("quiet@example.test"), api_client,
                 "finance_manager")  # fmt: skip
    prefer(g, "IMMEDIATE")
    off_track(g)
    report = send(g)
    assert (report.sent, report.failed) == (1, 0)
    assert len(mail.outbox) == 1  # the quiet user never chose emails
    message = mail.outbox[0]
    assert message.to == [g["owner"].email]
    assert message.subject == "Alert: Goal Revenue 12k is off track"
    assert "Demo Trading Ltd (Demo): a new alert." in message.body
    assert f"/w/{g['ws']['slug']}/e/{g['entity']['id']}/alerts" in message.body
    assert "gap to target" not in message.body  # the details (with amounts) stay in the app
    assert "The figures are in the app." in message.body
    assert "/api/alert-emails/unsubscribe?token=" in message.body
    assert send(g).sent == 0  # sent once
    assert prefer(g, "OFF", quiet)["mode"] == "OFF"

    # The link turns the emails off without signing in; a wrong token changes nothing.
    token = message.body.split("token=")[1].split()[0]
    anonymous = Client()  # not signed in
    assert anonymous.get("/api/alert-emails/unsubscribe?token=nope").json()["status"] == "unknown"
    done = anonymous.get(f"/api/alert-emails/unsubscribe?token={token}")
    assert done.json()["status"] == "off", done.content
    assert g["client"].get(URL.format(slug=g["ws"]["slug"])).json()["mode"] == "OFF"
    off_track(g, "Revenue 13k")
    assert send(g).sent == 0


def test_only_users_who_may_see_the_alert(g: dict[str, Any], make_user: Make,
                                          api_client: Make) -> None:  # fmt: skip
    budget(g)
    holder = join(g["client"], g["ws"]["slug"], make_user("holder@example.test"), api_client,
                  "budget_holder")  # fmt: skip
    prefer(g, "IMMEDIATE", holder, "el")
    off_track(g)
    assert send(g).sent == 0  # a budget holder cannot see goals
    assert mail.outbox == []


def test_daily_digest(g: dict[str, Any]) -> None:
    budget(g)
    prefer(g, "DIGEST", language="el")
    off_track(g)
    off_track(g, "Revenue 13k")
    assert send(g).sent == 0  # no immediate email in digest mode
    tomorrow = datetime.now(UTC) + timedelta(days=1)
    morning = tomorrow.replace(hour=6, minute=30)  # 08:30 or 09:30 in Cyprus
    report = send(g, morning)
    assert (report.digests, report.sent) == (1, 1)
    message = mail.outbox[0]
    assert message.subject.startswith("Σύνοψη ειδοποιήσεων")
    assert "- Goal Revenue 12k is off track" in message.body
    assert "- Goal Revenue 13k is off track" in message.body
    assert send(g, morning + timedelta(hours=2)).digests == 0  # once a day
    early = (tomorrow + timedelta(days=1)).replace(hour=4, minute=0)  # 06:00/07:00 in Cyprus
    assert send(g, early).digests == 0  # not before 08:00


def test_retries_then_failure_and_hourly_limit(
    g: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    budget(g)
    prefer(g, "IMMEDIATE")
    off_track(g)

    def broken(self: Any, fail_silently: bool = False) -> int:
        raise OSError("connection refused")

    monkeypatch.setattr("django.core.mail.EmailMessage.send", broken)
    now = datetime.now(UTC)
    assert send(g, now).retrying == 1
    set_context(tenant_id=UUID(g["ws"]["id"]))
    e = AlertEmail.objects.get()
    assert (e.attempts, e.status, e.last_error) == (1, "PENDING", "OSError: connection refused")
    assert e.next_attempt_at == now + timedelta(minutes=2)
    assert send(g, now + timedelta(minutes=1)).retrying == 0  # not due yet
    for minutes in (2, 6, 14, 30):
        send(g, now + timedelta(minutes=minutes + 1))
    set_context(tenant_id=UUID(g["ws"]["id"]))
    e.refresh_from_db()
    assert (e.attempts, e.status) == (5, "FAILED")
    monkeypatch.undo()

    with override_settings(ALERT_EMAILS_PER_HOUR=1):
        off_track(g, "Revenue 13k")
        off_track(g, "Revenue 14k")
        report = send(g)
        assert (report.sent, report.skipped) == (1, 1)
    set_context(tenant_id=UUID(g["ws"]["id"]))
    assert AlertEmail.objects.filter(status="SKIPPED").count() == 1


def test_the_scheduled_job_finds_the_workspaces(g: dict[str, Any]) -> None:
    budget(g)
    prefer(g, "IMMEDIATE")
    off_track(g)
    assert emails.send_all().sent == 1  # through dashboards_alert_email_tenant_ids()
    set_context(tenant_id=UUID(g["ws"]["id"]))
    assert AlertEmailPreference.objects.get().unsubscribe_token
