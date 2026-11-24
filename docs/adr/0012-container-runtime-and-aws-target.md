# ADR-0012: Container images on ECS Fargate behind CloudFront, one browser origin
Status: **Proposed** (implements the deployment section of planning doc 02; awaiting product owner review in PR) · Date: 2026-11-03
## Context
The product is a cloud-hosted SaaS used through a browser. ADR-0006 fixed the stack and AWS
eu-central-1. M1 shipped the application with local development tooling only. The application has
to be packaged so later environments (staging, pilot, production) run exactly what CI tested, with
no code changes between environments.
## Decision
- Two OCI images built from the repository: `fcp-backend` (Django + gunicorn, `fcp.settings.prod`)
  and `fcp-web` (built React app on unprivileged nginx). Both run as non-root users on a read-only root
  filesystem.
- On AWS: ECS Fargate for the API and one-off tasks (migrations, scheduled jobs), RDS PostgreSQL 17,
  CloudFront + WAF serving the app from S3 and routing `/api/*` and `/auth/*` to an ALB. The browser
  sees a single origin.
- Configuration only through environment variables and Secrets Manager. Deployed settings fail fast on
  missing or unsafe values (plain-HTTP identity provider, unencrypted database, empty host lists).
- Migrations never run on container start. They run as a separate task with the schema-owner role,
  after release approval.
- CI builds both images, checks the Dockerfiles with checkov, and runs a production-like smoke test.
  Nothing is pushed or deployed until a registry and environment are approved.
## Consequences
+ The same images run locally, in CI and on AWS. Horizontal scaling needs no code change (sessions in
  the database, stateless processes, transaction-local RLS context).
+ Single origin keeps `__Host-` cookies, strict CSRF and a strict CSP without CORS.
− Two images to maintain. Fargate costs more per vCPU than EC2, which is acceptable at pilot scale
  and can be revisited.
## Alternatives considered
App Runner (simpler, but less control over networking and one-off tasks); Lambda (cold starts,
long-running imports later); EKS (operational overhead not justified); serving the SPA from Django
(couples front-end releases to API releases and wastes API capacity).
