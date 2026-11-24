# ADR-0054: Alert emails through an outbox, titles only, off by default
Status: **Proposed** (M8-5, #194; awaiting product owner review in PR) · Date: 2026-11-17

## Context
Doc 10 §6.2 item 8 and the M8 brief (doc 22 §3, approved 2026-11-17) ask for the in-app alerts of
M4-7 also by email, immediately or as a daily digest, chosen by each user. Email leaves the
platform's access controls, so what it carries matters (data minimisation, threat T30). The
production sending service is a Gate P decision; development uses the local Mailpit catcher.

## Decision
- **Preferences** per user and workspace (`dashboards_alert_email_preference`): IMMEDIATE, DIGEST
  (08:00 Cyprus time) or OFF, in English or Greek. No row means off.
- **Content:** the alert's title, the entity's name, a link into the app and a one-click
  unsubscribe link. **Never the alert's details or any amount.** Titles are generated from goal
  and budget names and states and hold no figures.
- **Audience:** an email is queued only for users who may see the alert (its audience permission
  on the entity), checked when it is queued; a digest checks each alert when it is prepared.
- **Outbox** (`dashboards_alert_email`): queued in the same transaction as the alert, with a unique
  key per alert and user (and per user and day for digests), so nobody gets the same email twice.
  The scheduled job `dashboards_send_alert_emails` (every 5 minutes) prepares due digests and sends
  due emails through Django's SMTP backend; failures are retried after 2, 4, 8 and 16 minutes and
  marked FAILED after 5 attempts with the error kept. Above 20 immediate emails per user and hour,
  further ones are SKIPPED (the alerts stay in the app). Each sent email is audited.
- **Unsubscribe without signing in:** a random 256-bit token per preference; a narrow SECURITY
  DEFINER function turns off exactly the preference holding it and reveals nothing else. The job
  finds workspaces through another narrow function that returns IDs only, like the other jobs.

## Consequences
- Users who never opt in get no email.
- Production needs an SMTP service (Gate P, brief §7 item 6) and `APP_URL`, `SMTP_HOST`,
  `SMTP_PORT` and `DEFAULT_FROM_EMAIL` set; nothing else changes.
- Bounces and complaints are not processed yet; they come with the production service.
