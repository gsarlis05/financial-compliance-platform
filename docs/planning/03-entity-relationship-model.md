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
        string kind "FIRM|BUSINESS|PERSONAL"
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
        string entity_type "COMPANY|SOLE_TRADER|PARTNERSHIP|HOUSEHOLD"
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

## 6. Additions for customer types (see [11](11-account-types-and-coexistence.md))

```mermaid
erDiagram
    TENANT ||--o{ ENGAGEMENT : "grants (client side)"
    TENANT ||--o{ ENGAGEMENT : "receives (firm side)"
    ENGAGEMENT ||--o{ ENGAGEMENT_ASSIGNMENT : "staffed by"
    MEMBERSHIP ||--o{ ENGAGEMENT_ASSIGNMENT : "firm member"
    TENANT ||--o{ FEATURE_ENTITLEMENT : has
    LEGAL_ENTITY ||--o{ DIMENSION : defines
    DIMENSION ||--o{ DIMENSION_VALUE : has
    ROLE_ASSIGNMENT }o--o{ DIMENSION_VALUE : "scoped to (optional)"

    ENGAGEMENT {
        uuid id PK
        uuid client_tenant_id FK
        uuid firm_tenant_id FK
        string scope "BOOKKEEPING|TAX|AUDIT_READ|CFO_ADVISORY_READ"
        jsonb permission_ceiling
        uuid_array legal_entity_ids
        timestamptz valid_from
        timestamptz valid_until
        uuid approved_by_client_user
        string status "PROPOSED|ACTIVE|SUSPENDED|REVOKED|EXPIRED"
    }
    ENGAGEMENT_ASSIGNMENT {
        uuid id PK
        uuid engagement_id FK
        uuid firm_membership_id FK
        uuid role_id FK
    }
    FEATURE_ENTITLEMENT {
        uuid tenant_id
        string feature_key
        bool enabled
        string source "KIND_DEFAULT|PLAN|ADMIN"
    }
    DIMENSION {
        uuid id PK
        uuid tenant_id
        uuid legal_entity_id
        string kind "DEPARTMENT|PROJECT|COST_CENTRE|CUSTOM"
        string name
    }
    DIMENSION_VALUE {
        uuid id PK
        uuid tenant_id
        uuid dimension_id
        string code
        string name
        uuid parent_id
        string status
    }
```

`ENGAGEMENT` is the only table that references two tenants. It is readable by both sides through
a dedicated RLS policy (`tenant_id IN (client_tenant_id, firm_tenant_id)` evaluated against the
session's tenant), and writable only through the engagement workflow.

## 7. Supporting registers needed by FP&A (Phases 1–3)

```mermaid
erDiagram
    LEGAL_ENTITY ||--o{ COUNTERPARTY : has
    COUNTERPARTY ||--o{ OPEN_ITEM : owes
    JOURNAL_ENTRY ||--o| OPEN_ITEM : "creates (invoice)"
    OPEN_ITEM ||--o{ OPEN_ITEM_SETTLEMENT : "settled by"
    LEGAL_ENTITY ||--o{ RECURRING_OBLIGATION : has
    LEGAL_ENTITY ||--o{ DEBT_INSTRUMENT : has
    DEBT_INSTRUMENT ||--|{ DEBT_SCHEDULE_LINE : "generated schedule"
    LEGAL_ENTITY ||--o{ FIXED_ASSET : has
    LEGAL_ENTITY ||--o{ TAX_PAYMENT_CALENDAR : has

    COUNTERPARTY {
        uuid id PK
        uuid tenant_id
        uuid legal_entity_id
        string kind "CUSTOMER|SUPPLIER|BOTH|EMPLOYEE|TAX_AUTHORITY|LENDER"
        string name_enc
        string vat_no_enc
        int payment_terms_days
        int observed_days_late "derived, nullable"
        int days_late_override
    }
    OPEN_ITEM {
        uuid id PK
        uuid tenant_id
        uuid legal_entity_id
        uuid counterparty_id
        string side "RECEIVABLE|PAYABLE"
        string document_no
        date issue_date
        date due_date
        numeric amount_txn
        char currency
        numeric open_amount_txn
        uuid source_entry_id
        string status "OPEN|PARTIAL|SETTLED|WRITTEN_OFF|DISPUTED"
    }
    OPEN_ITEM_SETTLEMENT {
        uuid id PK
        uuid open_item_id
        uuid settling_entry_id
        date settled_on
        numeric amount_txn
    }
    RECURRING_OBLIGATION {
        uuid id PK
        uuid tenant_id
        uuid legal_entity_id
        string name
        string category
        numeric amount
        char currency
        string schedule_rule "RRULE-like"
        string business_day_adjustment
        date start_date
        date end_date
        bool contractual
        uuid counterparty_id
    }
    DEBT_INSTRUMENT {
        uuid id PK
        uuid tenant_id
        uuid legal_entity_id
        string kind "TERM_LOAN|OVERDRAFT|REVOLVER|LEASE|DIRECTOR_LOAN"
        numeric principal
        numeric facility_limit
        date start_date
        date maturity_date
        string rate_type "FIXED|VARIABLE"
        numeric fixed_rate
        string reference_rate_key
        numeric margin
        string day_count "ACT_360|ACT_365|30_360"
        string repayment_type "ANNUITY|LINEAR|BULLET|IO_THEN_ANNUITY"
        string frequency
    }
    DEBT_SCHEDULE_LINE {
        uuid debt_instrument_id
        date due_date
        numeric principal
        numeric interest
        numeric closing_balance
        string schedule_version
    }
    FIXED_ASSET {
        uuid id PK
        uuid tenant_id
        uuid legal_entity_id
        string asset_class
        date acquisition_date
        numeric cost
        int useful_life_months
        string method "STRAIGHT_LINE|REDUCING_BALANCE"
        numeric residual_value
        date disposal_date
    }
    TAX_PAYMENT_CALENDAR {
        uuid id PK
        uuid tenant_id
        uuid legal_entity_id
        string tax_kind "VAT|CIT_PROVISIONAL|CIT_FINAL|SDC|SOCIAL_INSURANCE|OTHER"
        date due_date
        numeric amount
        string nature "COMMITTED|EXPECTED"
        string basis "MANUAL|TAX_MODULE"
        uuid rule_version_id "source of due-date rule"
    }
```

## 8. Planning (FP&A) entities (see [10](10-cfo-fpa-specification.md))

All are tenant-owned with RLS. **None of them has an FK *into* posted-ledger rows that would allow
modification**. They reference ledger data only by key (account, period, watermark).

```mermaid
erDiagram
    TAXONOMY_VERSION ||--|{ TAXONOMY_LINE : contains
    ACCOUNT ||--o{ ACCOUNT_TAXONOMY_MAP : "mapped by"
    TAXONOMY_LINE ||--o{ ACCOUNT_TAXONOMY_MAP : "maps to"
    LEGAL_ENTITY ||--o{ PLAN : has
    PLAN ||--|{ PLAN_VERSION : versions
    PLAN_VERSION ||--o{ PLAN_LINE : contains
    PLAN_VERSION ||--o| ASSUMPTION_SET : "driven by"
    ASSUMPTION_SET ||--|{ ASSUMPTION : contains
    SCENARIO }o--|| PLAN_VERSION : "based on"
    SCENARIO ||--|{ SCENARIO_OVERRIDE : "ordered overrides"
    CALC_RUN }o--o| PLAN_VERSION : "evaluates"
    CALC_RUN }o--o| SCENARIO : "evaluates"
    CALC_RUN ||--o{ CALC_RESULT : produces
    CALC_RESULT ||--o{ CALC_LINEAGE : "explained by"
    METRIC_DEFINITION ||--|{ METRIC_DEFINITION_VERSION : versions
    GOAL }o--|| METRIC_DEFINITION_VERSION : measures
    GOAL ||--o{ GOAL_EVALUATION : "evaluated by"
    GOAL_EVALUATION }o--|| CALC_RUN : "uses"
    PLAN_VERSION ||--o{ VARIANCE_EXPLANATION : "explained"
    REPORT_PACK ||--|{ REPORT_SECTION : contains
    REPORT_PACK }o--o{ CALC_RUN : "snapshots"
    DASHBOARD ||--|{ WIDGET : contains
    ALERT_RULE ||--o{ ALERT : raises
    OPERATIONAL_METRIC ||--o{ OPERATIONAL_METRIC_VALUE : values

    TAXONOMY_VERSION {
        uuid id PK
        string key "IFRS_SME_CY|PERSONAL"
        string semver
        string status
    }
    TAXONOMY_LINE {
        uuid id PK
        uuid taxonomy_version_id
        string code "REV.SALES"
        string statement "PL|BS|CF|MEMO"
        string sign_convention
        string direction "HIGHER_BETTER|LOWER_BETTER"
        uuid parent_id
    }
    ACCOUNT_TAXONOMY_MAP {
        uuid tenant_id
        uuid account_id
        uuid taxonomy_line_id
        date valid_from
    }
    PLAN {
        uuid id PK
        uuid tenant_id
        uuid legal_entity_id
        string kind "BUDGET|ROLLING_FORECAST|CASH_FORECAST_13W|PROJECTION"
        string name
        uuid fiscal_year_id
        string granularity "DAY|WEEK|MONTH"
    }
    PLAN_VERSION {
        uuid id PK
        uuid tenant_id
        uuid plan_id
        int version_no
        string label "Original|Revision 1"
        string status "DRAFT|SUBMITTED|APPROVED|LOCKED|SUPERSEDED|PUBLISHED"
        uuid supersedes_id
        text revision_reason
        bigint actuals_watermark
        date cutover_date
        bytea content_hash
        uuid approved_by
        timestamptz approved_at
    }
    PLAN_LINE {
        uuid tenant_id
        uuid plan_version_id
        uuid taxonomy_line_id
        uuid account_id "optional, finer grain"
        uuid_array dimension_value_ids
        date period_start
        string nature "BUDGET|FORECAST|COMMITTED|EXPECTED"
        numeric amount
        string phasing_method
        uuid owner_user_id
    }
    ASSUMPTION_SET {
        uuid id PK
        uuid tenant_id
        int version_no
        string status
        bytea content_hash
    }
    ASSUMPTION {
        uuid id PK
        uuid assumption_set_id
        string driver_key "revenue_growth|gross_margin|dso|capex|interest_rate"
        string target_ref
        date period_from
        date period_to
        numeric value
        string unit
        text rationale
        uuid source_document_id
    }
    SCENARIO {
        uuid id PK
        uuid tenant_id
        uuid base_plan_version_id
        string name
        string status "DRAFT|SHARED|ARCHIVED"
        uuid created_by
    }
    SCENARIO_OVERRIDE {
        uuid id PK
        uuid scenario_id
        int seq
        string type "PCT_CHANGE|ABS_CHANGE|TIMING_SHIFT|NEW_DEBT|NEW_HIRE|CAPEX|ONE_OFF|RATE_CHANGE"
        jsonb params "schema-validated per type"
        text rationale
    }
    CALC_RUN {
        uuid id PK
        uuid tenant_id
        uuid legal_entity_id
        string kind "CASH_13W|ROLLING|PROJECTION_3S|KPI|GOAL|SCENARIO|SENSITIVITY"
        string engine_version
        bigint actuals_watermark
        date as_of_date
        jsonb input_refs
        bytea input_hash
        bytea output_hash
        string status "RUNNING|VALID|INVALID|FAILED"
        jsonb invariant_results
        bool stale
        bool is_published
        string trigger "USER|SYSTEM_EVENT|SCHEDULE"
    }
    CALC_RESULT {
        uuid tenant_id
        uuid calc_run_id
        string series_key "taxonomy line / KPI / cash category"
        uuid_array dimension_value_ids
        date period_start
        string granularity
        string nature
        numeric value
        string unit
        string nm_reason "not meaningful reason"
    }
    CALC_LINEAGE {
        uuid calc_run_id
        string series_key
        date period_start
        string input_kind "ACTUAL|ASSUMPTION|OVERRIDE|OPEN_ITEM|SCHEDULE|FORMULA"
        string input_ref
    }
    METRIC_DEFINITION {
        uuid id PK
        uuid tenant_id "null = standard library"
        string key
        string category
        string visibility "PRIVATE|WORKSPACE|STANDARD"
    }
    METRIC_DEFINITION_VERSION {
        uuid id PK
        uuid metric_definition_id
        int version_no
        text formula_dsl
        string unit
        string direction
        jsonb conventions
        string status "DRAFT|APPROVED|RETIRED"
        uuid approved_by
    }
    GOAL {
        uuid id PK
        uuid tenant_id
        uuid legal_entity_id
        string scope_kind "WORKSPACE|ENTITY|DEPARTMENT|PROJECT|INDIVIDUAL"
        uuid scope_ref
        uuid metric_version_id
        string target_type "ABSOLUTE|RELATIVE_PCT|MIN_THRESHOLD|MAX_THRESHOLD"
        numeric target_value
        date target_date
        string measurement_window
        numeric baseline_value
        date baseline_date
        uuid baseline_calc_run_id
        numeric materiality_threshold
        uuid linked_plan_id
        uuid owner_user_id
        int version_no
        string status
    }
    GOAL_EVALUATION {
        uuid id PK
        uuid goal_id
        uuid calc_run_id
        numeric actual_to_date
        numeric projected_outcome
        numeric gap_to_target
        jsonb required_performance
        string status "ON_TRACK|AT_RISK|OFF_TRACK|ACHIEVED|MISSED|NOT_MEASURABLE"
        jsonb driver_contributions
    }
    VARIANCE_EXPLANATION {
        uuid id PK
        uuid tenant_id
        uuid plan_version_id
        string comparison "BUDGET_VS_ACTUAL|FORECAST_VS_ACTUAL"
        uuid taxonomy_line_id
        uuid_array dimension_value_ids
        date period_start
        numeric variance_amount
        text explanation
        uuid author_id
        int version_no
    }
    REPORT_PACK {
        uuid id PK
        uuid tenant_id
        uuid legal_entity_id
        uuid template_id
        date period_start
        date period_end
        bigint actuals_watermark
        string status "DRAFT|IN_REVIEW|FINAL"
        bytea snapshot_hash
        uuid finalised_by
    }
    REPORT_SECTION {
        uuid id PK
        uuid report_pack_id
        string kind
        jsonb data_snapshot
        text commentary
        string commentary_origin "HUMAN|AI_DRAFT_ACCEPTED"
    }
    DASHBOARD {
        uuid id PK
        uuid tenant_id
        uuid owner_user_id "null = workspace default"
        string name
    }
    WIDGET {
        uuid id PK
        uuid dashboard_id
        string type
        jsonb query
        jsonb layout
    }
    ALERT_RULE {
        uuid id PK
        uuid tenant_id
        string subject_kind "GOAL|BUDGET_LINE|CASH_MIN|KPI|DATA_QUALITY"
        uuid subject_ref
        jsonb condition
        string severity
    }
    ALERT {
        uuid id PK
        uuid tenant_id
        uuid alert_rule_id
        uuid calc_run_id
        string status "OPEN|ACKNOWLEDGED|RESOLVED"
        timestamptz raised_at
    }
    OPERATIONAL_METRIC {
        uuid id PK
        uuid tenant_id
        string key "customers|headcount|mrr"
        string unit
    }
    OPERATIONAL_METRIC_VALUE {
        uuid tenant_id
        uuid operational_metric_id
        date period_start
        numeric value
        string source "MANUAL|IMPORT|INTEGRATION"
        uuid entered_by
    }
```

Additional constraints:
- `PLAN_VERSION` with status `APPROVED|LOCKED|PUBLISHED` and its `PLAN_LINE`s are immutable (trigger), as are `CALC_RUN`/`CALC_RESULT` once `VALID` and `REPORT_PACK` once `FINAL`.
- `CALC_RESULT.nature` is `NOT NULL`, with a `CHECK` that `ACTUAL` values only appear in runs whose lineage marks them as ledger-derived.
- At most one `PUBLISHED` version per rolling plan at a time (partial unique index).
- **Read model for actuals:** `fact_actuals_monthly(tenant_id, legal_entity_id, account_id, dimension_set_id, period_start, debit, credit, watermark)` and `fact_cash_daily(...)` are derived tables refreshed on posting. They are **rebuildable from the ledger at any time** and verified by the nightly integrity job.
