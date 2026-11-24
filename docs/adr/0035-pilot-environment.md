# ADR-0035: The pilot environment is complete as code and is created only on the owner's approval
Status: **Proposed** (M5-5; awaiting product owner review in PR) · Date: 2026-11-10

## Context
Gate P is the owner's own use of the platform with real data. ADR-0010 requires a separate AWS
account in an EU region for it, and the directive forbids creating any AWS resource without the
owner's explicit approval. ADR-0012 fixed the shape: container images on ECS Fargate behind
CloudFront, with one origin for the browser. M0 delivered the network, keys, database and document
storage as Terraform modules. Issue #78 asks for the rest, a backup and restore drill, and
monitoring.

## Decision
- **`infra/terraform/envs/pilot`** composes the whole environment. It is checked in CI (`fmt`,
  `validate`, tflint, Checkov) and **never applied** by CI or by any script. The apply steps, for
  an operator after written approval, are in `docs/runbooks/pilot-environment.md`.
- **No public subnets and no NAT gateway.** Tasks reach AWS services through VPC endpoints. The
  load balancer is internal; CloudFront reaches it through a VPC origin, so the firewall cannot
  be bypassed.
- **New modules:**
  - `registry`: private image repository, immutable tags, scan on push, customer-managed key.
  - `endpoints`: interface endpoints (registry, logs, secrets, keys) and the S3 gateway endpoint.
  - `app`: ECS cluster; API service and bank-import worker with the database **runtime** role;
    a separate `ops` task definition with the **owner** role for migrations and the nightly
    checks; internal HTTPS load balancer; Secrets Manager entries (values are set by an
    operator and are never in Terraform state); EventBridge schedules for the audit-chain,
    ledger-integrity and actuals checks and the 15-minute cash forecast refresh.
  - `edge`: CloudFront with the same security headers as the nginx image, a private bucket for
    the built web app, and AWS WAF (IP reputation, known bad inputs including Log4j, the common
    rule set, a rate limit per address). Firewall logs are stored in the EU region, with cookies
    and tokens redacted.
  - `monitoring`: one encrypted alarm topic for database CPU and storage, server errors,
    unhealthy or missing API tasks, error-level log lines, and any task that stops with an error
    (which covers the nightly checks and migrations).
  - `backup`: a locked AWS Backup vault with daily (35 days) and monthly (1 year) copies of the
    database, on top of the database's own point-in-time recovery; failed jobs raise an alarm.
- **The image is referenced by digest.** The `app` module refuses a tag. CI produces an SPDX
  bill of materials for both images. Signing (cosign) happens at release, by the operator, with
  a key in the pilot account (runbook).
- **Error tracking without a third party.** The application already logs redacted JSON; an
  error-level line raises an alarm. A hosted error tracker would receive application data and
  is left as an owner decision.
- **The restore drill is a script** (`make restore-drill`): backup, restore to a scratch
  database, identical row counts in every table, and the application's own integrity checks on
  the restored copy. It runs against the local stack today; the same checks apply to an AWS
  Backup restore (runbook).

## Consequences
- Nothing exists on AWS. Creating the pilot needs the owner's approval and these decisions:
  the AWS account, the domain and its certificates, the alarm address, where the identity
  provider runs, and how the antivirus service gets its signature updates.
- AWS requires the firewall and certificate of a CloudFront distribution in `us-east-1`. Only
  those two are created there; no customer data is stored there.
- Without a NAT gateway, the tasks cannot call the internet. An identity provider outside the
  VPC, or antivirus signature updates, need a controlled way out (a proxy or NAT with an
  allow-list). That is part of the two open decisions above.
- The common firewall rules would block request bodies over 8 KB. That one rule only counts,
  because uploads are a core feature and the application enforces its own limits.
- Automatic secret rotation, geo restriction, cross-region copies and origin failover are left
  for the production design (Gate G). Each exception is written next to the resource.
