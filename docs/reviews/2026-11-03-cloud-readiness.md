# Architecture review: cloud-hosted SaaS readiness (2026-11-03)

Question from the product owner: confirm that we are building a fully cloud-hosted SaaS web
application used through a browser; check whether the existing code is structured for that and ready
for later deployment to AWS; list the changes needed; confirm that development can continue without
rebuilding; and state how much of the planned functionality is implemented and tested.

**Short answer:** yes, it is a browser-based multi-tenant SaaS web application by design, and nothing
needs to be rebuilt. What was missing was the *deployment packaging*: container images, production
settings, a production app server and a readiness probe. That is added in M2-0 (this PR). The AWS
infrastructure itself (compute, load balancer, CDN, firewall) remains planned for M5-5 and needs your
approval before anything is created.

## 1. Is it structured as a web application?
Yes.

| Layer | What exists | Cloud-hosted SaaS property |
|---|---|---|
| Browser client | React 19 + TypeScript single-page app (`frontend/`), English/Greek | Runs in any modern browser; no desktop install |
| API | Django 5.2 + Django Ninja JSON API under `/api/`, OpenAPI published | Stateless HTTP; scales horizontally behind a load balancer |
| Sign-in | OIDC with mandatory MFA, backend-for-frontend sessions | Works with any OIDC provider (Keycloak locally; Keycloak on AWS or a managed IdP later) |
| Multi-tenancy | Workspaces, PostgreSQL row-level security on every tenant table | One deployment serves many customers, isolated in the database itself |
| Data | PostgreSQL 17 | Maps 1:1 to Amazon RDS for PostgreSQL 17 |
| Files (from M2-4) | S3 API (SeaweedFS locally) | Maps 1:1 to Amazon S3 |

## 2. Is it ready for future deployment to AWS?
The application code was already written for the cloud. These are the 12-factor properties checked
in this review:
- **Configuration from environment variables only.** There are no secrets in code, and the app fails
  loudly when a required value is missing. On AWS these values come from Secrets Manager and Parameter
  Store through the ECS task definition.
- **Stateless processes.** Sessions are stored in the database, nothing is written to local disk (checked:
  no file writes in application code), and the row-level security context is transaction-local, so
  persistent database connections are safe. Any number of API containers can run.
- **Logs** are JSON lines on stdout, redacted by an allow-list, and ready for CloudWatch Logs.
- **Liveness probe** at `/healthz`.
- **Migrations** run as a separate step with a separate database role (`DB_ROLE=owner`). On AWS this
  becomes a one-off ECS task, so the runtime role never owns the schema.
- **Scheduled jobs** (integrity checks, audit verification) are management commands. On AWS this
  becomes an EventBridge Scheduler rule that runs an ECS task.
- **Same-origin design.** The browser talks to one origin (`/` for the app, `/api` and `/auth` for the
  backend), which maps to one CloudFront distribution with two origins (S3 for the app, the load
  balancer for the API). `__Host-` cookies and strict CSRF keep working unchanged.
- **Terraform skeleton** (M0-7) for staging: network, KMS keys, RDS PostgreSQL, S3. It is validated in
  CI and never applied.

Gaps found (none requires changing existing features):

| Gap | Impact | Fixed in |
|---|---|---|
| No container images | Nothing to run on ECS | **M2-0** (backend and web images, non-root, health checks) |
| No production settings module (HTTPS redirect, HSTS, proxy headers, DB TLS, no `localhost` defaults) | Unsafe or broken behind a load balancer | **M2-0** (`fcp.settings.prod`, verified by `manage.py check --deploy` in CI) |
| Development server only | Not production-grade | **M2-0** (gunicorn) |
| No readiness probe (database reachable) | The load balancer could route to an instance that cannot serve | **M2-0** (`/readyz`) |
| No IaC for compute, ALB, CloudFront, WAF, ECR, Secrets Manager, schedules | Cannot deploy yet | M5-5 (pilot IaC), or earlier if you ask; never applied without your approval |
| Identity provider hosting not decided | Needed before the pilot | Decision for M5-5: Keycloak on ECS (as now) or a managed IdP. The code is IdP-agnostic |
| No error tracker, metrics or alarms | Operations visibility | M5-5 (CloudWatch alarms, error tracking) |

## 3. Architectural changes needed
None to the architecture. Additive packaging work only (above). The approved design (modular monolith,
row-level security, BFF auth, rules as data, isolated AI gateway) is unchanged. The target AWS
topology is in [docs/deployment/aws.md](../deployment/aws.md).

## 4. Can we continue without rebuilding?
Yes. All existing features stay as they are. M2 (registers, banking, reporting) builds on the M1
ledger exactly as planned. Each new module follows the same patterns: row-level security, audit,
permission per route, problem+json errors, and API-first with the UI on top. So every feature stays
cloud-compatible by construction, and CI enforces it (route permission check, RLS schema check,
import contracts, and now `check --deploy` and the image build).

## 5. How much is implemented and tested?
Measured against the approved backlog (planning doc 08), weighted by the size estimates
(S = 1, M = 2, L = 4):

| Scope | Done | Total | Share |
|---|---|---|---|
| Phase 1 (M0–M2): accounting foundation | M0 + M1 = 37 | 65 | 57% |
| Phase 1–2 (M0–M5): up to the owner pilot | 37 | 124 | **30%** |
| Whole roadmap (Phases 1–5, M0–M13)* | 37 | ≈ 310 | **≈ 12%** |

\* Phases 3–5 (M6–M13) are planned at milestone level only; they are estimated here at the average
size of M2–M4 (≈ 23 points each).

Everything that is implemented is tested. That covers 610 backend tests (98.5% line / 90.6% branch
coverage on the domain modules; posting code is 100% covered), 12 frontend tests including
accessibility checks, and live end-to-end runs against a real identity provider. Your 20% estimate
sits between the two measures. The finished work is the hardest-to-change part (security, tenancy,
immutable ledger), so later milestones build on it rather than around it. Most *visible* features
(bank import, statements, VAT, forecasts, budgets, dashboards, AI) are still ahead.

## Decision record
- Continue with the roadmap as planned. M2-0 (cloud packaging) is inserted before M2-1 because it is
  small and protects compatibility from now on.
- No AWS resources are created. Infrastructure for compute and the CDN is drafted no earlier than
  M5-5, and only applied with your explicit approval.
