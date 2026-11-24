# ADR-0016: Document vault: S3 per-tenant prefixes, SSE-KMS tenant context, ClamAV service
Status: **Proposed** (M2-4; awaiting product owner review in PR) · Date: 2026-11-04
## Context
Invoices, receipts and contracts are evidence for the books and contain personal and confidential
data. They come from outside, so they can carry malware or pretend to be another file type
(threat model: uploads). The deployment target is AWS (ADR-0012). Containers have read-only root
filesystems, and nothing may be kept on local disk.
## Decision
- **Storage:** S3 API only (boto3).
  - SeaweedFS locally and in CI; AWS S3 when deployed.
  - Keys are `tenants/<tenant>/documents/<document>`. The storage adapter refuses any key outside
    the caller's tenant prefix, as a second line behind row-level security.
  - When deployed, every object is written with **SSE-KMS** and an encryption context
    `{"tenant_id": …}`. An object can only be decrypted with its tenant's context, and KMS logs
    every use in CloudTrail.
  - Deployed settings fail fast without `DOCUMENTS_KMS_KEY_ID`, and a custom S3 endpoint must be
    https.
- **Upload pipeline**, all before anything is stored:
  1. permission;
  2. size (10 MB);
  3. type: an allowlist (PDF, PNG, JPEG, XLSX, CSV, TXT, XML), and the content, sniffed from its
     bytes, must match the extension;
  4. the same content in the same legal entity is the same document (idempotent);
  5. **ClamAV** over TCP (INSTREAM). It runs as a separate service (GPL-2.0, never linked into the
     application) and **fails closed**: no scan, no storage (503);
  6. store, then record.
- **Evidence:**
  - Documents are immutable, and users cannot delete them: a database trigger blocks it, and the
    runtime role has no UPDATE or DELETE on the table.
  - Links to entries and open items (posted control-account lines) can be added and removed.
  - Retention and disposal (Cyprus: at least six years) will be a platform job.
- **Downloads** are always attachments, with the sniffed content type, `nosniff` and `no-store`.
  The stored hash is checked on every read.
- **No content in logs or audit:** events carry the name, type, size and SHA-256. Malware
  refusals record the signature name only. Uploads, links and **downloads** are audited.
## Consequences
+ AC-M2-4 holds end to end, and is tested against real ClamAV and S3 in CI:
  - EICAR refused;
  - type mismatch refused;
  - no cross-tenant reads;
  - no content in logs or audit.
+ No local disk; the same code runs on SeaweedFS and S3.
− Two more services to run: ClamAV (an ECS service with signature updates through freshclam, or
  GuardDuty Malware Protection for S3 later) and the bucket with its KMS key (IaC with the staging
  environment).
− Uploads are scanned synchronously. 10 MB scans take well under a second, but a ClamAV outage
  blocks uploads by design.
− Bank statement files (M2-5) still keep their raw copy in the database. Moving them into the vault
  is a follow-up.
