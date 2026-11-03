# 01 — Product Requirements Document (PRD)

Status: **DRAFT for review** · Owner: Product · Related: [00](00-review-and-assumptions.md), [08 backlog](08-implementation-backlog.md)

## 1. Vision

A trustworthy, auditable platform where Cyprus (and later EU) accounting firms, auditors, tax
professionals and businesses keep books, compute taxes and prepare compliance outputs. Every number
must be traceable to its source, its rule version and the human who approved it.

## 2. Personas

| Persona | Description | Primary jobs |
|---|---|---|
| **Firm Partner** (ICPAC member) | Owns client relationships, signs off | Review and approve filings and statements; manage staff access |
| **Accountant / Bookkeeper** | Day-to-day processing for many clients | Post journals, reconcile banks, close periods, prepare VAT |
| **Tax Professional** | Tax computations and advice | Corporate tax and VAT computations; review rule applicability; document judgments |
| **Auditor** | External/statutory audit | Read-only access to client books, working papers, evidence requests, sampling; never edits client ledger |
| **Business Owner / Finance Manager** (SME) | Runs own books or collaborates with firm | Upload documents, approve, view reports |
| **Tenant Administrator** | Manages organisation settings and users | Users, roles, MFA policy, integrations, AI settings |
| **Platform Operator** (our staff) | Runs the SaaS | Ops, support via **audited, time-boxed, customer-approved** access only |
| **Rules Curator** (qualified professional) | Maintains regulatory rule packs | Encode, test, peer-review and publish rule versions |

## 3. Scope by release

### MVP (Milestones 1–3): "Trustworthy ledger + VAT"
- Multi-tenant org/firm model with client entities, users, roles, MFA, SSO-ready.
- Chart of accounts (Cyprus/IFRS-aligned template, customisable), fiscal years and periods.
- Double-entry journals: draft → submitted → approved → posted; reversal and adjustment workflows; period close/lock.
- Multi-currency transactions in EUR functional currency, with FX rates stored per date and source.
- Trial balance, general ledger, account activity; basic balance sheet / P&L with IFRS line mapping.
- Document vault (invoices, receipts, contracts) with hashes, links to entries, and retention.
- Bank statement import (CSV, CAMT.053) and reconciliation.
- VAT: VAT codes, rule-engine-driven VAT calculation, VAT return preparation (data for VAT4 form) with reviewer sign-off and export. No automatic submission.
- Immutable audit/evidence trail and an evidence export package.

### Phase 2: "Tax"
- Corporate income tax computation (adjustments, losses with carry-forward limits, 2025/2026 boundary), SDC computations, IR4 preparation data.
- Rules curation UI, official worked-example test suites.
- AI assistant (read-only): explain calculations, find inconsistencies, draft memos.

### Phase 3: "Audit & statements"
- IFRS financial statement drafting with notes scaffolding, and an XBRL/iXBRL export (if required).
- Audit engagement module: materiality, working papers, PBC (provided-by-client) requests, sampling, sign-off chain. **No automated opinion.**

### Phase 4: "EU expansion & e-invoicing"
- Jurisdiction packs (Greece next is assumed), EN 16931 / Peppol adapter, ViDA readiness, OSS/VIES.

### Explicitly out of scope (until approved)
Payroll and Social Insurance submissions, automated filing to government portals, payments
initiation, investment/crypto valuation engines, and AI-generated opinions or filings.

## 4. Functional requirements (MVP)

IDs are referenced by backlog items and tests.

**Tenancy & access**
- FR-T1 A tenant (firm or business) owns one or more **legal entities** (clients). All data is entity-scoped within a tenant.
- FR-T2 Firm users can be granted access to a subset of client entities only.
- FR-T3 Auditor access is a separate, read-only, time-bound grant approved by the entity's owner/firm.
- FR-T4 MFA is mandatory for all users. Tenant admins can require SSO.

**Ledger** (see [05](05-financial-ledger-spec.md))
- FR-L1 Journal entries balance per currency-converted functional amount, and every line has a non-zero amount.
- FR-L2 Posted entries are immutable. Corrections happen only by reversal or adjusting entry, with a reason and approval.
- FR-L3 Periods can be soft-closed (posting only with an elevated permission) and hard-locked (no posting). Unlocking requires dual approval and is audited.
- FR-L4 Segregation of duties: the preparer cannot approve their own entry when the entity policy requires it (configurable thresholds).
- FR-L5 Trial balance always balances. Reports reconcile to the ledger by construction and by automated checks.

**Tax**
- FR-X1 Tax computations run only through the versioned rules engine. Each result records the rule-pack version, inputs and the trace.
- FR-X2 Regulated outputs (VAT return, tax computation) require human review and sign-off before export, and are frozen afterwards.
- FR-X3 Professional judgments (e.g. classification of an exempt supply) are captured as **Judgment Records** with rationale, references and approver.

**Evidence**
- FR-E1 Every state change to financial or professional records produces an append-only, hash-chained audit event.
- FR-E2 Users can export an evidence pack (entries, documents, approvals, rule versions, hash proofs) for a period.

**AI** (phase 2, but constraints apply to design now)
- FR-A1 AI is off by default per tenant. Admins enable it explicitly and choose the permitted data classes.
- FR-A2 AI outputs are labelled as drafts and cite only verified sources from the retrieval index. Uncertain interpretations are flagged "requires professional review".
- FR-A3 AI has no write access to the ledger, filings or rules. It can only create drafts that enter normal approval workflows.

## 5. Non-functional requirements

| Area | Requirement |
|---|---|
| Correctness | Decimal arithmetic only; explicit, documented rounding per rule; zero tolerance for an unbalanced posted entry |
| Security | OWASP ASVS L2 baseline (L3 for auth/ledger/tenancy); MFA; encryption in transit (TLS 1.2+) and at rest; tenant isolation enforced in the DB |
| Privacy | GDPR: DPA, sub-processor register, data-subject request tooling, EU data residency, minimisation in logs/AI |
| Auditability | Append-only, tamper-evident audit log; time from trusted NTP source; retention per record class with legal hold |
| Availability | 99.5% MVP target (99.9% later); RPO ≤ 15 min, RTO ≤ 4 h (to confirm) |
| Performance | Trial balance for an entity with 1M lines in < 3 s (p95) using balance snapshots |
| Accessibility | WCAG 2.2 AA |
| Localisation | EN/EL UI; locale-aware number/date formatting; Greek statutory labels |
| Operability | Zero-downtime deploys; migrations reviewed and never auto-applied to production without approval |

## 6. Success metrics (initial)
- Zero unbalanced posted entries and zero cross-tenant access incidents (hard invariants, continuously monitored).
- VAT return preparation time reduced ≥ 50% vs the customer's baseline (pilot measurement).
- 100% of regulated outputs carry reviewer sign-off and rule-version trace.

## 7. Risks
| Risk | Mitigation |
|---|---|
| Incorrect tax rules cause wrong filings | Curator + peer review, official worked-example tests, effective dating, human sign-off, liability terms |
| Regulatory change outpaces releases | Rule packs are data, deployable independently of code, with a change-monitoring process |
| Over-reliance on AI | Read-only AI, mandatory citations, review gates, UI labelling |
| Data breach / cross-tenant leak | DB-enforced RLS, per-tenant keys, isolation test suite, pen-tests |
| Scope creep | Phase gates, and this PRD is the reference for "unrelated features" |
