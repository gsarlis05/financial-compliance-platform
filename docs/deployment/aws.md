# Deployment target: AWS (eu-central-1)

Status: **design + container packaging only.** No AWS resource exists. Creating or changing any
environment needs the product owner's explicit approval (directive; ADR-0010). Staging carries
synthetic data only.

## Topology
```
 Browser ──HTTPS──► CloudFront (+ AWS WAF) ─┬─ /*            ──► S3 bucket: built web app (private, OAC)
                                            └─ /api/*, /auth/* ──► ALB (HTTPS) ──► ECS Fargate: API (fcp-backend image)
                                                                                     │  private subnets, no public IP
                         EventBridge Scheduler ──► ECS one-off tasks: integrity checks, audit verification
                         Release pipeline      ──► ECS one-off task: migrate (DB_ROLE=owner)
                                                                                     ▼
                                     RDS PostgreSQL 17 (Multi-AZ, KMS, TLS verify-full) · S3 (documents, SSE-KMS, Object Lock)
                                     Secrets Manager (DB passwords, Django key, OIDC secret) · CloudWatch Logs
 Identity provider: Keycloak on ECS (same images as local) or a managed OIDC provider (decision at M5-5)
```
One origin for the browser (`https://app.<domain>`), so the `__Host-` session cookie, strict CSRF
and the Content Security Policy work exactly as in local development (Vite proxy) and in the
production-like smoke test (nginx web image).

## Images (built in CI, never pushed until a registry is approved)
| Image | Contents | Runs as | Notes |
|---|---|---|---|
| `fcp-backend` (`backend/Dockerfile`) | Django + gunicorn, `fcp.settings.prod` | uid 10001, read-only root FS | Amazon RDS CA bundle included; `/healthz` liveness, `/readyz` readiness (database) |
| `fcp-web` (`frontend/Dockerfile`) | built app on unprivileged nginx | uid 101, read-only root FS (tmpfs for `/tmp`, `/etc/nginx/conf.d`) | Used for local production-like runs; on AWS the same `dist/` goes to S3 behind CloudFront |

## Runtime configuration (environment variables → ECS task definition)
| Variable | Source on AWS | Notes |
|---|---|---|
| `DJANGO_SECRET_KEY` | Secrets Manager | ≥ 50 random characters |
| `DJANGO_ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | task definition | `app.<domain>` / `https://app.<domain>` |
| `POSTGRES_HOST`, `POSTGRES_DB` | task definition | RDS endpoint |
| `POSTGRES_APP_USER/PASSWORD` | Secrets Manager | API and web service: runtime role (no schema rights, no BYPASSRLS) |
| `POSTGRES_OWNER_USER/PASSWORD` + `DB_ROLE=owner` | Secrets Manager | **migration and ops tasks only** |
| `POSTGRES_SSLMODE` | default `verify-full` | `require`/`verify-ca` allowed; plain-text connections are refused at start-up |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_REDIRECT_URI`, `OIDC_POST_LOGOUT_REDIRECT_URI` | task definition | must be `https://` |
| `OIDC_CLIENT_SECRET` | Secrets Manager | |
| `FORWARDED_ALLOW_IPS` | task definition | VPC CIDR of the ALB subnets (who may set `X-Forwarded-*`) |
| `GUNICORN_WORKERS`, `GUNICORN_THREADS` | task definition | defaults 3 × 2 |

`fcp.settings.prod` refuses to start if a value is missing or unsafe (http URLs, TLS disabled,
empty host lists). `manage.py check --deploy` runs in CI with no warnings.

## Operations mapping
| Concern | Local | AWS |
|---|---|---|
| Migrations | `make migrate` | one-off ECS task `python manage.py migrate` with `DB_ROLE=owner`, run by the release pipeline after approval |
| Nightly checks | `make ops-checks` | EventBridge Scheduler → ECS task `ledger_integrity_check`, `audit_verify`; non-zero exit → alarm |
| Bank statement imports (M2-5) | parsed inline in development (`BANKING_PROCESS_INLINE`) | ECS service `python manage.py banking_process_imports --loop` (runtime role, 1 task; scale on the pending count later). Never inline in deployed settings (ADR-0015) |
| Documents (M2-4) | SeaweedFS + ClamAV (`make services`; `make dev` creates the bucket) | S3 bucket (block public access, versioning) with SSE-KMS (`DOCUMENTS_KMS_KEY_ID`, tenant encryption context); task role limited to `tenants/*` objects; ClamAV as an internal ECS service (`CLAMD_HOST`), signatures updated by freshclam; both from IaC with the staging environment (ADR-0016) |
| Logs | stdout JSON | CloudWatch Logs (same JSON, already redacted) |
| Health | `/healthz`, `/readyz` | ALB target group health check `/readyz`; container health check `/healthz` |
| Scaling | one process | ECS service auto scaling on CPU/requests; sessions in the DB, no sticky sessions needed |

## Verified today
`make container-smoke` (also a CI job) runs both images production-like: TLS `verify-full` to
PostgreSQL 17, migration as a separate owner-role task, API as the runtime role on a read-only root
filesystem as a non-root user, web front end proxying the API on one origin with security headers,
readiness probe, and the scheduled-job commands.

## Still to build (M5-5, pilot readiness; nothing is applied without approval)
Terraform for ECR, ECS cluster/services/tasks, ALB, CloudFront + WAF, Secrets Manager entries,
EventBridge schedules, CloudWatch alarms and dashboards; image signing (cosign) and SBOM; error
tracking; backup/restore drill; identity provider hosting decision.
