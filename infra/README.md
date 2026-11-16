# Infrastructure

**Nothing in this directory is applied to any cloud account without the product owner's explicit
approval** (development directive; ADR-0010). CI runs static checks only (`fmt`, `validate` with
`-backend=false`, tflint, Checkov) and fails if any `terraform apply`/`destroy`/`import` command
appears in workflows, scripts or the Makefile.

```
local/                 Local development services used by compose.yaml (never deployed)
terraform/
  modules/kms          Customer-managed keys per data class (database, documents, logs, backups), annual rotation
  modules/network      Private VPC: app and data subnets in pinned AZs, locked default SG, encrypted flow logs
  modules/database     PostgreSQL 17: private, KMS-encrypted, TLS forced, Multi-AZ by default, deletion
                       protection, PITR backups, Secrets Manager master password, no statement logging
  modules/storage      Documents/evidence bucket: private, versioned, SSE-KMS, TLS-only, deny unencrypted
                       uploads, Object Lock (GOVERNANCE in staging, COMPLIANCE in production), access logs
  envs/staging         Composition for staging (synthetic data only), EU regions only, account allow-list
```

## Checks
`make iac-check` (Docker; needs Terraform registry access). Checkov exceptions are written inside
the resource with a reason (`# checkov:skip=ID:reason`) and are reviewed like code.

## Applying (future, approval required)
1. Product owner approves the change and the target account in writing (PR comment).
2. An operator runs `terraform init -backend-config=<approved backend file>` and `terraform plan`.
3. The plan output is reviewed and approved.
4. Only then `terraform apply` of that reviewed plan, by the operator, outside CI.

## Licensing
Terraform CLI 1.6+ is BUSL-1.1. Using it to manage our own infrastructure is permitted. The
configuration is also compatible with OpenTofu (MPL-2.0) should we prefer it.
