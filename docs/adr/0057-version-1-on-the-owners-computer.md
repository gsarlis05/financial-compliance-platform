# ADR-0057: Version 1 on the owner's computer: the production images, local services, backups
Status: **Accepted** (V1-3, #209; owner decision 2026-11-22: "computer first, AWS later") · Date: 2026-11-22

## Context
Version 1 is used by the owner alone, on their own computer, before any AWS environment (Gate P).
It must:
- install with one command;
- survive restarts;
- back up and restore everything;
- upgrade safely;
- keep the security properties the platform already has: MFA sign-in, a separate migration
  role, row-level security, the audit chain.

## Decision
- **The same container images as for AWS**, so the owner runs what CI tests:
  - `fcp-backend` runs the API (gunicorn), the import worker, a scheduled-jobs container and the
    migration as a one-off service;
  - `fcp-web` (nginx) serves the app and forwards `/api` and `/auth`.

  Containers are read-only with `/tmp` in memory.
- **Local services** in `deploy/local/compose.yaml`:
  - PostgreSQL 17 (the platform's database, and a separate `keycloak` database);
  - Keycloak in production mode, with the realm `fcp` imported (password and TOTP; brute-force
    protection);
  - SeaweedFS for documents;
  - ClamAV;
  - Mailpit for emails.

  Every port binds to 127.0.0.1. Data lives in named volumes.
- **Settings `fcp.settings.local`:** debug off and the worker parses imports. The app is served
  at `http://localhost:8088`: browsers treat localhost as a secure origin, so the `__Host-`
  cookies work without TLS.
- **Sign-in addresses:** the backend reads the provider's configuration inside the container
  network (`OIDC_METADATA_URL`), while browsers use `http://localhost:8080`. Keycloak's dynamic
  back-channel gives each its own address, and the token issuer stays the browser's.
- **Scheduled jobs** as on AWS:
  - alert emails every 5 minutes;
  - cash-forecast and projection refresh every 15 minutes;
  - nightly audit, ledger and actuals checks, and workspace purges (owner role).
- **`scripts/local/fcp.sh`** does install, start, stop, status, logs, backup, restore, upgrade
  and verify.
  - **install** writes random secrets to `deploy/local/.env` (mode 600, never committed) and
    creates the owner's sign-in. The temporary password is shown once; changing it and setting up
    TOTP are required at first sign-in.
  - **backup** writes one archive with checksums. It holds both databases, the documents and the
    secrets (without them a restore could not sign in or read documents), so the owner keeps it
    safe.
  - **restore** verifies the checksums, asks for confirmation and recreates the volumes. It
    restores as the superuser, so every object keeps its owner (some functions must stay owned
    by `fcp_maintenance`), then runs the integrity checks.
  - **upgrade** backs up, rebuilds from the checkout and lets the migration service run before
    the API starts.

## Verification
`scripts/local/smoke.js` drives a real browser through the local stack. On 2026-11-23 it ran
from a clean install:
1. First sign-in: the temporary password must be changed and an authenticator set up, then a
   workspace is created.
2. The temporary password is refused afterwards, and repeated failures lock the account for a
   while (brute-force protection).
3. A backup, then a restore over everything (the integrity checks pass), then signing in again
   with the new password and code: the workspace is still there.
4. An upgrade: backup, rebuild, migrate, checks.

This run found that the realm had not enabled the "update password" required action, so the
temporary password stayed valid. The realm now enables it.

## Consequences
- The owner needs Docker and about 4 GB of memory. ClamAV alone takes about 1 GB.
- No TLS on localhost. The platform is not reachable from other machines; moving to AWS is
  Gate P, with its own environment and the same images.
- Emails go to the local Mailpit only, until a real email service is chosen (Gate P).
