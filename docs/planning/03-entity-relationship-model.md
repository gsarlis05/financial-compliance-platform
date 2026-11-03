# 03 — Initial Entity-Relationship Model

Status: **DRAFT for review**. This is a logical model. Physical DDL will be produced in Milestone 1 after approval.

Conventions (all tenant-owned tables):
- `id UUID` (v7, time-ordered) as PK, plus `tenant_id UUID NOT NULL` with an RLS policy. FKs to tenant-owned tables are **composite** `(tenant_id, id)` so a row cannot reference another tenant's row even by bug.
- `created_at`, `created_by` on every table; `updated_at`, `updated_by` only on mutable tables.
- Money is `NUMERIC(19,4)` + `currency CHAR(3)`; rates are `NUMERIC(28,10)`.
- No hard deletes of financial/professional records. Records carry a `status` plus retention handling.

## 1. Tenancy & identity

```mermaid
erDiagram
    TENANT ||--o{ LEGAL_ENTITY : owns
    TENANT ||--o{ MEMBERSHIP : has
    USER ||--o{ MEMBERSHIP : "belongs via"
    MEMBERSHIP ||--o{ ROLE_ASSIGNMENT : has
    ROLE ||--o{ ROLE_ASSIGNMENT : granted
    ROLE ||--o{ ROLE_PERMISSION : contains
    LEGAL_ENTITY ||--o{ ROLE_ASSIGNMENT : "scoped to (nullable = all entities)"
    LEGAL_ENTITY ||--o{ ACCESS_GRANT : "external access (auditor)"
    USER ||--o{ ACCESS_GRANT : receives

    TENANT {
        uuid id PK
        string name
        string kind "FIRM|BUSINESS"
        string data_region
        string status
        jsonb security_policy
    }
    LEGAL_ENTITY {
        uuid id PK
        uuid tenant_id FK
        string legal_name
        string registration_no
        string tax_id_enc
        string vat_no_enc
        string jurisdiction "CY"
        char functional_currency
        date incorporation_date
        string entity_type
        string status
    }
    USER {
        uuid id PK
        string idp_subject UK
        string email
        string display_name
        string locale
        string status
    }
    MEMBERSHIP {
        uuid id PK
        uuid tenant_id FK
        uuid user_id FK
        string status
        timestamptz invited_at
    }
    ROLE {
        uuid id PK
        uuid tenant_id "null = system role"
        string key
        string name
    }
    ROLE_PERMISSION {
        uuid role_id FK
        string permission
    }
    ROLE_ASSIGNMENT {
        uuid id PK
        uuid tenant_id
        uuid membership_id FK
        uuid role_id FK
        uuid legal_entity_id "nullable"
        timestamptz valid_until
    }
    ACCESS_GRANT {
        uuid id PK
        uuid tenant_id
        uuid legal_entity_id FK
        uuid grantee_user_id FK
        string grant_type "AUDITOR_READ"
        timestamptz valid_from
        timestamptz valid_until
        uuid approved_by
        string status
    }
```

`USER` is global (one person may belong to several tenants, e.g. a freelance auditor). Everything a
user can see is resolved through `MEMBERSHIP` + `ROLE_ASSIGNMENT` + `ACCESS_GRANT`.

## 2. Ledger

```mermaid
erDiagram
    LEGAL_ENTITY ||--o{ ACCOUNT : "chart of accounts"
    ACCOUNT ||--o{ ACCOUNT : "parent"
    LEGAL_ENTITY ||--o{ FISCAL_YEAR : has
    FISCAL_YEAR ||--|{ PERIOD : contains
    LEGAL_ENTITY ||--o{ JOURNAL : "journals (GJ, SALES, PURCH, BANK)"
    JOURNAL ||--o{ JOURNAL_ENTRY : contains
    PERIOD ||--o{ JOURNAL_ENTRY : "posted in"
    JOURNAL_ENTRY ||--|{ JOURNAL_LINE : has
    ACCOUNT ||--o{ JOURNAL_LINE : "debited/credited"
    JOURNAL_ENTRY |o--o| JOURNAL_ENTRY : "reverses"
    JOURNAL_LINE }o--o| TAX_CODE : "tax code"
    JOURNAL_LINE }o--o| DIMENSION_VALUE : "cost centre/project"
    ACCOUNT ||--o{ ACCOUNT_BALANCE : aggregates
    PERIOD ||--o{ ACCOUNT_BALANCE : "per period"
    FX_RATE }o--|| CURRENCY : quotes
    JOURNAL_ENTRY }o--o{ DOCUMENT : "supported by (DOCUMENT_LINK)"

    ACCOUNT {
        uuid id PK
        uuid tenant_id
        uuid legal_entity_id
        string code
        string name_en
        string name_el
        string type "ASSET|LIABILITY|EQUITY|INCOME|EXPENSE"
        string normal_side
        bool is_postable
        string ifrs_mapping_key
        char currency "null = any"
        string status
    }
    FISCAL_YEAR {
        uuid id PK
        uuid legal_entity_id
        date start_date
        date end_date
        string status "OPEN|CLOSED"
    }
    PERIOD {
        uuid id PK
        uuid fiscal_year_id
        int number
        date start_date
        date end_date
        bool is_adjustment_period
        string status "OPEN|SOFT_CLOSED|LOCKED"
    }
    JOURNAL_ENTRY {
        uuid id PK
        uuid tenant_id
        uuid legal_entity_id
        uuid journal_id
        string entry_no "gapless per journal+FY on post"
        date accounting_date
        date document_date
        uuid period_id
        string status "DRAFT|SUBMITTED|APPROVED|POSTED|REJECTED|VOID_DRAFT"
        string entry_type "STANDARD|REVERSAL|ADJUSTMENT|OPENING|CLOSING|FX_REVAL"
        uuid reverses_entry_id
        uuid reversed_by_entry_id
        text description
        text correction_reason
        uuid prepared_by
        uuid approved_by
        timestamptz posted_at
        uuid posted_by
        string source "MANUAL|IMPORT|BANK|SYSTEM|AI_DRAFT"
        string idempotency_key
        bytea content_hash
    }
    JOURNAL_LINE {
        uuid id PK
        uuid tenant_id
        uuid entry_id
        int line_no
        uuid account_id
        numeric debit_txn
        numeric credit_txn
        char txn_currency
        numeric fx_rate
        uuid fx_rate_id
        numeric debit_func
        numeric credit_func
        uuid tax_code_id
        numeric tax_base_func
        uuid counterparty_id
        text memo
    }
    ACCOUNT_BALANCE {
        uuid tenant_id
        uuid account_id
        uuid period_id
        char currency
        numeric debit_total
        numeric credit_total
        bigint version
    }
    FX_RATE {
        uuid id PK
        char base
        char quote
        date rate_date
        numeric rate
        string source "ECB|MANUAL"
        uuid source_document_id
    }
```

## 3. Tax, rules, judgments

```mermaid
erDiagram
    RULE_PACK ||--|{ RULE_VERSION : versions
    RULE_VERSION ||--|{ RULE_TEST_CASE : "verified by"
    RULE_VERSION }o--|{ SOURCE_REFERENCE : "cites"
    SOURCE_REFERENCE }o--|| SOURCE_DOCUMENT : "points into"
    RULE_VERSION ||--o{ TAX_CODE : "defines (VAT codes)"
    LEGAL_ENTITY ||--o{ TAX_COMPUTATION : has
    TAX_COMPUTATION }o--|| RULE_VERSION : "evaluated with"
    TAX_COMPUTATION ||--o| TAX_RETURN : "feeds"
    TAX_COMPUTATION ||--o{ JUDGMENT_RECORD : "relies on"
    TAX_RETURN ||--o{ SIGNOFF : "signed by"

    RULE_PACK {
        uuid id PK
        string key "CY.VAT|CY.CIT|CY.SDC"
        string jurisdiction
        string domain
    }
    RULE_VERSION {
        uuid id PK
        uuid rule_pack_id
        string semver
        date effective_from
        date effective_to
        string period_basis "TRANSACTION_DATE|TAX_YEAR|SUPPLY_DATE"
        jsonb definition
        bytea definition_hash
        string status "DRAFT|IN_REVIEW|APPROVED|PUBLISHED|RETIRED"
        uuid authored_by
        uuid reviewed_by
        uuid published_by
        timestamptz published_at
    }
    SOURCE_DOCUMENT {
        uuid id PK
        string title
        string issuer
        string jurisdiction
        string url
        date published_date
        date retrieved_at
        bytea sha256
        string language
        string verification_status
        uuid verified_by
    }
    SOURCE_REFERENCE {
        uuid id PK
        uuid source_document_id
        string locator "article/section/page"
        text excerpt
    }
    RULE_TEST_CASE {
        uuid id PK
        uuid rule_version_id
        string name
        string origin "OFFICIAL_EXAMPLE|CURATOR|REGRESSION"
        jsonb input
        jsonb expected_output
        uuid source_reference_id
    }
    TAX_CODE {
        uuid id PK
        uuid rule_version_id
        string code
        string description
        string treatment "STANDARD|REDUCED|ZERO|EXEMPT|REVERSE_CHARGE|OUT_OF_SCOPE"
        string vat_return_box_mapping
    }
    TAX_COMPUTATION {
        uuid id PK
        uuid tenant_id
        uuid legal_entity_id
        string kind "VAT_RETURN|CIT"
        date period_start
        date period_end
        uuid rule_version_id
        bytea input_snapshot_hash
        jsonb result
        jsonb trace
        string status "DRAFT|IN_REVIEW|APPROVED|FINAL|SUPERSEDED"
        uuid supersedes_id
    }
    TAX_RETURN {
        uuid id PK
        uuid tenant_id
        uuid computation_id
        string form "VAT4|IR4"
        jsonb box_values
        string status "PREPARED|SIGNED_OFF|EXPORTED|FILED_EXTERNALLY"
        string external_reference
        date filed_on
    }
    JUDGMENT_RECORD {
        uuid id PK
        uuid tenant_id
        uuid legal_entity_id
        string subject
        text question
        text conclusion
        text rationale
        jsonb source_reference_ids
        string materiality
        uuid prepared_by
        uuid approved_by
        string status
    }
    SIGNOFF {
        uuid id PK
        uuid tenant_id
        string subject_type
        uuid subject_id
        uuid user_id
        string role_capacity
        bytea subject_hash
        timestamptz signed_at
    }
```

`RULE_*` and `SOURCE_*` are **platform-global** (not tenant-owned). They are read-only to tenants and
writable only by the curator role in a separate admin surface.

## 4. Documents, workflow, audit, AI

```mermaid
erDiagram
    LEGAL_ENTITY ||--o{ DOCUMENT : stores
    DOCUMENT ||--o{ DOCUMENT_LINK : "linked to subject"
    APPROVAL_REQUEST ||--|{ APPROVAL_STEP : steps
    TENANT ||--o{ AUDIT_EVENT : "hash chain"
    AI_REQUEST ||--o| AI_DRAFT : produces

    DOCUMENT {
        uuid id PK
        uuid tenant_id
        uuid legal_entity_id
        string storage_key
        string filename
        string mime_type_detected
        bigint size
        bytea sha256
        string scan_status "PENDING|CLEAN|INFECTED|FAILED"
        string classification "CONFIDENTIAL|INTERNAL|PERSONAL_DATA"
        string retention_class
        date retain_until
        bool legal_hold
        uuid kms_key_ref
    }
    DOCUMENT_LINK {
        uuid tenant_id
        uuid document_id
        string subject_type
        uuid subject_id
    }
    APPROVAL_REQUEST {
        uuid id PK
        uuid tenant_id
        string subject_type
        uuid subject_id
        bytea subject_hash
        string policy_key
        string status
        uuid requested_by
    }
    APPROVAL_STEP {
        uuid id PK
        uuid request_id
        int seq
        string required_permission
        uuid decided_by
        string decision
        text comment
        timestamptz decided_at
    }
    AUDIT_EVENT {
        bigint seq PK
        uuid tenant_id
        uuid event_id
        timestamptz occurred_at
        uuid actor_user_id
        string actor_type "USER|SYSTEM|SUPPORT|AI_GATEWAY"
        string action
        string subject_type
        uuid subject_id
        jsonb before_digest
        jsonb after_digest
        string ip_hash
        string correlation_id
        bytea prev_hash
        bytea hash
    }
    AI_REQUEST {
        uuid id PK
        uuid tenant_id
        uuid user_id
        string task
        jsonb context_refs
        string data_classes
        string prompt_version
        string model_id
        timestamptz created_at
    }
    AI_DRAFT {
        uuid id PK
        uuid tenant_id
        uuid request_id
        text content
        jsonb citations
        jsonb uncertainty_flags
        string status "DRAFT|ACCEPTED|DISCARDED"
        uuid reviewed_by
    }
```

## 5. Key integrity constraints (DB-enforced)

| Constraint | Mechanism |
|---|---|
| Line has exactly one side, positive | `CHECK ((debit_txn > 0 AND credit_txn = 0) OR (credit_txn > 0 AND debit_txn = 0))`, same for `_func` |
| Entry balances in functional currency | `CONSTRAINT TRIGGER … DEFERRABLE INITIALLY DEFERRED` on entry status → POSTED: `SUM(debit_func) = SUM(credit_func)` and ≥ 2 lines |
| Posted entries immutable | `BEFORE UPDATE OR DELETE` trigger rejects changes to POSTED entries/lines (the only allowed update is setting `reversed_by_entry_id` once) |
| Posting only in OPEN period (or SOFT_CLOSED with privilege flag) | Trigger checks `period.status`; `accounting_date` within period dates |
| Account postable and same entity | Composite FK `(tenant_id, legal_entity_id, account_id)` + trigger on `is_postable` |
| Gapless entry numbers | Per-(journal, fiscal year) counter row locked `FOR UPDATE` at posting |
| Audit log append-only | `REVOKE UPDATE, DELETE` from the app role; trigger as backstop |
| Cross-tenant references impossible | Composite FKs including `tenant_id` + RLS |
| Published rule versions immutable, non-overlapping effective ranges per pack | Trigger + `EXCLUDE USING gist (rule_pack_id WITH =, daterange(effective_from, effective_to) WITH &&) WHERE status='PUBLISHED'` |
