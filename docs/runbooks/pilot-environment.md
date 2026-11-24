# Runbook: creating and releasing to the pilot environment

**Nothing here is done without the product owner's explicit, written approval** (a comment on the
pull request or issue that names the account and the change). CI never applies anything, and no
script in this repository does.

## Decisions needed first (owner)
| Decision | Used for |
|---|---|
| The separate AWS account for the pilot | `allowed_account_ids` |
| The domain, e.g. `app.example.com`, and its two certificates (region and `us-east-1`) | `app_host`, `regional_certificate_arn`, `global_certificate_arn` |
| Where the identity provider runs (Keycloak in the account, or a managed provider) | `oidc_issuer` |
| How the antivirus service runs and gets signature updates | `clamd_host` |
| Who receives alarms | `alarm_email` |

## Create the environment (operator, after approval)
1. Build the API image from the approved commit, push it to the pilot repository and note its
   **digest**. Sign it and attach the bill of materials (see *Release* below).
2. `terraform init -backend-config=<approved backend file>` in `infra/terraform/envs/pilot`.
3. `terraform plan -out=pilot.plan` with the variables above. Send the plan to the owner.
4. After the owner approves **that plan**: `terraform apply pilot.plan`.
5. Fill in the secrets listed in the output `secrets_to_fill` (Secrets Manager console or CLI,
   never in a file in the repository):
   - `django-secret-key`: at least 50 random characters;
   - `database-runtime` and `database-owner`: `{"username": "...", "password": "..."}` for the
     two database roles, created with `scripts/db/create_roles.sql`;
   - `oidc-client-secret`: from the identity provider.
6. Run the migration as a one-off task with the `ops` task definition
   (`python manage.py migrate`), then `python manage.py seed_reference_data`.
7. Upload the built web app (`frontend/dist`) to the web bucket: hashed assets with a long cache
   time, `index.html` with `Cache-Control: no-store`.
8. Point the DNS record of the host at the output `distribution_domain_name`.
9. Confirm the alarm subscription e-mail, then check: sign-in with MFA, `/readyz` through the
   load balancer target group, one upload, and that a deliberately failed task raises an alarm.
10. Run the pilot restore drill (`docs/runbooks/backup-restore-drill.md`).

## Release (each new version)
1. CI is green on the commit, including the image build, the production-like smoke test and
   the bill of materials (artifact `sbom`).
2. Build and push the image; note the digest.
3. Sign the digest and attach the bill of materials, with a signing key held in the pilot
   account's KMS:
   `cosign sign --key awskms:///<key> <repository>@<digest>` and
   `cosign attest --key awskms:///<key> --type spdxjson --predicate fcp-backend.spdx.json <repository>@<digest>`.
4. `terraform plan` with the new `image` digest; the owner approves the plan; apply it.
5. Run the migration task before the new API tasks take traffic when the release has migrations.
6. Upload the web app and invalidate `index.html` on the distribution.

## Roll back
Apply the previous image digest (the service's deployment circuit breaker already rolls back a
version that does not become healthy). Migrations are written to be backward compatible for one
release; a database problem is handled with the restore drill's steps, never by editing data.
