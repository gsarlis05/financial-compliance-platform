"""Alert emails (M8-5, brief 22 §3, AC-EM1).

- **Preferences** per user and workspace: immediately, a daily digest (08:00 Cyprus time) or off.
  The default is off. Every email has a one-click link that turns it off without signing in.
- **What an email says:** the alert's title, the entity's name and a link into the app; **never
  amounts or details** (data minimisation: figures stay behind sign-in). English or Greek, as the
  user chose.
- **Who gets one:** only users who chose emails and may see the alert (its audience permission on
  the entity, checked when the email is queued and again when it is sent).
- **Delivery:** an outbox. An alert is queued at most once per user (a unique key); digests once
  per user and day. The scheduled sender (``dashboards_send_alert_emails``) sends what is due,
  retries failures after 2, 4, 8 and 16 minutes, and gives up after 5 attempts with the error
  recorded. Above ``ALERT_EMAILS_PER_HOUR`` immediate emails per user, further ones are skipped
  (the alerts stay in the app). Everything is audited.
"""

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import connection, transaction
from django.utils import timezone

from fcp.core.db.rls import set_context
from fcp.core.errors import DomainError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.tenancy.api import LegalEntity, Tenant, WorkspaceContext, enter_workspace

from .models import Alert, AlertEmail, AlertEmailPreference

log = logging.getLogger(__name__)
Mode = AlertEmailPreference.Mode
NICOSIA = ZoneInfo("Europe/Nicosia")
MAX_ATTEMPTS = 5
_TEXT = {
    "en": {"subject": "Alert: {title}", "digest": "Your alerts for {day}",
           "intro": "{entity}: a new alert.", "digest_intro": "New alerts since your last digest:",
           "open": "Open the alerts (sign in first): {url}",
           "stop": "Stop these emails: {url}",
           "note": "This email gives titles only. The figures are in the app."},
    "el": {"subject": "Ειδοποίηση: {title}", "digest": "Σύνοψη ειδοποιήσεων, {day}",
           "intro": "{entity}: νέα ειδοποίηση.",
           "digest_intro": "Νέες ειδοποιήσεις από την τελευταία σύνοψη:",
           "open": "Δείτε τις ειδοποιήσεις (με σύνδεση): {url}",
           "stop": "Διακοπή αυτών των μηνυμάτων: {url}",
           "note": "Στο μήνυμα εμφανίζονται μόνο τίτλοι· ποσά υπάρχουν μόνο στην εφαρμογή."},
}  # fmt: skip


# --- preferences ----------------------------------------------------------------------------------


def preference(ctx: WorkspaceContext) -> AlertEmailPreference | None:
    return AlertEmailPreference.objects.filter(user=ctx.user).first()


@transaction.atomic
def choose(ctx: WorkspaceContext, mode: str, language: str) -> AlertEmailPreference:
    """Your alert emails in this workspace: IMMEDIATE, DIGEST or OFF, in English or Greek."""
    found, made = AlertEmailPreference.objects.get_or_create(
        user=ctx.user,
        defaults={"tenant": ctx.tenant, "unsubscribe_token": secrets.token_urlsafe(32)},
    )  # fmt: skip
    before = None if made else found.mode
    found.mode, found.language = mode, language
    if mode == Mode.DIGEST and before != Mode.DIGEST:
        found.last_digest_on = timezone.localdate(timezone=NICOSIA)  # from today onwards
    found.save()
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id,
          action="dashboards.alert_email.preference", subject_type="user",
          subject_id=ctx.user.id, changes={"mode": mode, "before": before,
                                           "language": language})  # fmt: skip
    return found


def unsubscribe(token: str) -> bool:
    """The one-click link: turn off the preference holding ``token`` (no sign-in needed)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT dashboards_alert_email_unsubscribe(%s)", [token[:100]])
        row = cursor.fetchone()
    return bool(row and row[0])


# --- queueing -------------------------------------------------------------------------------------


def _link(slug: str, entity_id: UUID) -> str:
    return f"{settings.APP_URL}/w/{slug}/e/{entity_id}/alerts"


def _stop_link(p: AlertEmailPreference) -> str:
    return f"{settings.APP_URL}/api/alert-emails/unsubscribe?token={p.unsubscribe_token}"


def _may_see(user: Any, slug: str, alert: Alert) -> bool:
    try:
        return enter_workspace(user, slug).can(alert.audience, alert.legal_entity_id)
    except DomainError:
        return False


def _entity_name(ctx: WorkspaceContext, entity_id: UUID) -> str:
    name = LegalEntity.objects.filter(id=entity_id).values_list("legal_name", flat=True).first()
    return name or ctx.tenant.name


def on_alert(ctx: WorkspaceContext, alert: Alert) -> int:
    """Queue an immediate email of ``alert`` for every user who chose them and may see it."""
    queued = 0
    slug, tenant_id = ctx.tenant.slug, ctx.tenant.id
    wanted = list(AlertEmailPreference.objects.filter(mode=Mode.IMMEDIATE)
                  .select_related("user"))  # fmt: skip
    for p in wanted:
        if not _may_see(p.user, slug, alert):
            continue
        set_context(tenant_id=tenant_id, user_id=ctx.user.id)  # back to the caller's context
        t = _TEXT[p.language if p.language in _TEXT else "en"]
        body = "\n\n".join([t["intro"].format(entity=_entity_name(ctx, alert.legal_entity_id)),
                            alert.title, t["open"].format(url=_link(slug, alert.legal_entity_id)),
                            t["note"], t["stop"].format(url=_stop_link(p))])  # fmt: skip
        _, made = AlertEmail.objects.get_or_create(
            dedupe_key=f"alert:{alert.id}:{p.user_id}",
            defaults={"tenant_id": tenant_id, "user": p.user, "kind": AlertEmail.Kind.IMMEDIATE,
                      "alert_ids": [str(alert.id)],
                      "subject": t["subject"].format(title=alert.title)[:250], "body": body,
                      "next_attempt_at": timezone.now()},
        )  # fmt: skip
        queued += int(made)
    set_context(tenant_id=tenant_id, user_id=ctx.user.id)
    return queued


def _digest(tenant: Tenant, p: AlertEmailPreference, today: date) -> AlertEmail | None:
    since = datetime.combine(p.last_digest_on or today, datetime.min.time(), tzinfo=NICOSIA)
    found = [a for a in Alert.objects.filter(created_at__gte=since).order_by("created_at")
             if _may_see(p.user, tenant.slug, a)]  # fmt: skip
    set_context(tenant_id=tenant.id)
    p.last_digest_on = today
    p.save(update_fields=["last_digest_on", "updated_at"])
    if not found:
        return None
    t = _TEXT[p.language if p.language in _TEXT else "en"]
    lines = [f"- {a.title}" for a in found]
    entities = sorted({a.legal_entity_id for a in found})
    body = "\n\n".join([t["digest_intro"], "\n".join(lines),
                        *(t["open"].format(url=_link(tenant.slug, e)) for e in entities),
                        t["note"], t["stop"].format(url=_stop_link(p))])  # fmt: skip
    made, _ = AlertEmail.objects.get_or_create(
        dedupe_key=f"digest:{today.isoformat()}:{p.user_id}:{tenant.id}",
        defaults={"tenant_id": tenant.id, "user": p.user, "kind": AlertEmail.Kind.DIGEST,
                  "alert_ids": [str(a.id) for a in found],
                  "subject": t["digest"].format(day=today.isoformat()), "body": body,
                  "next_attempt_at": timezone.now()},
    )  # fmt: skip
    return made


# --- sending --------------------------------------------------------------------------------------


@dataclass
class SendReport:
    sent: int = 0
    failed: int = 0
    retrying: int = 0
    skipped: int = 0
    digests: int = 0
    errors: list[str] = field(default_factory=list)


def _deliver(e: AlertEmail, now: datetime, report: SendReport) -> None:
    hour_ago = now - timedelta(hours=1)
    recent = AlertEmail.objects.filter(user=e.user, kind=AlertEmail.Kind.IMMEDIATE,
                                       status=AlertEmail.Status.SENT,
                                       sent_at__gte=hour_ago).count()  # fmt: skip
    if e.kind == AlertEmail.Kind.IMMEDIATE and recent >= settings.ALERT_EMAILS_PER_HOUR:
        e.status, e.last_error = AlertEmail.Status.SKIPPED, "hourly limit reached"
        e.save(update_fields=["status", "last_error"])
        report.skipped += 1
        return
    e.attempts += 1
    try:
        EmailMessage(e.subject, e.body, to=[e.user.email]).send(fail_silently=False)
    except Exception as failure:  # noqa: BLE001 (any transport error is retried, then recorded)
        e.last_error = f"{type(failure).__name__}: {failure}"[:500]
        if e.attempts >= MAX_ATTEMPTS:
            e.status = AlertEmail.Status.FAILED
            report.failed += 1
        else:
            e.next_attempt_at = now + timedelta(minutes=2**e.attempts)
            report.retrying += 1
        e.save(update_fields=["attempts", "last_error", "status", "next_attempt_at"])
        log.warning("alert email %s not sent (attempt %s): %s", e.id, e.attempts, e.last_error)
        return
    e.status, e.sent_at = AlertEmail.Status.SENT, now
    e.save(update_fields=["attempts", "status", "sent_at"])
    audit(tenant_id=e.tenant_id, actor_user_id=None, action="dashboards.alert_email.sent",
          subject_type="alert_email", subject_id=e.id,
          changes={"kind": e.kind, "alerts": len(e.alert_ids)})  # fmt: skip
    report.sent += 1


def digest_due(now: datetime, p: AlertEmailPreference) -> bool:
    local = now.astimezone(NICOSIA)
    return (p.mode == Mode.DIGEST and local.hour >= settings.ALERT_DIGEST_HOUR
            and p.last_digest_on is not None and p.last_digest_on < local.date())  # fmt: skip


def send_all(now: datetime | None = None,
             tenants: Callable[[], list[UUID]] | None = None) -> SendReport:  # fmt: skip
    """The scheduled pass: prepare due digests, then send every due email, workspace by
    workspace, each under its own row-level security context."""
    now = now or timezone.now()
    report = SendReport()
    if tenants is None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT dashboards_alert_email_tenant_ids()")
            ids = [row[0] for row in cursor.fetchall()]
    else:
        ids = tenants()
    for tenant_id in ids:
        with transaction.atomic():
            set_context(tenant_id=tenant_id)
            tenant = Tenant.objects.get(id=tenant_id)
            for p in AlertEmailPreference.objects.select_related("user"):
                if digest_due(now, p):
                    report.digests += int(_digest(tenant, p, now.astimezone(NICOSIA).date())
                                          is not None)  # fmt: skip
        with transaction.atomic():
            set_context(tenant_id=tenant_id)
            due = list(AlertEmail.objects.select_for_update(skip_locked=True)
                       .filter(status=AlertEmail.Status.PENDING, next_attempt_at__lte=now)
                       .select_related("user").order_by("created_at"))  # fmt: skip
            for e in due:
                _deliver(e, now, report)
    return report
