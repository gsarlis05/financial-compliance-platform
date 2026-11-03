# 00 — Input Review, Assumptions and Open Questions

Status: **APPROVED (2026-11-03)** · Date: 2026-11-03 · Scope: first assignment (planning only, no application code)

> **Update (v2):** Scope expanded to FP&A/CFO intelligence and three customer types (firm, business, personal). Assumptions A-1 and A-2 are superseded by [PRD v2](01-product-requirements.md) and the [master plan](../MASTER-PLAN.md). The consolidated open decisions are in MASTER-PLAN §8.

## 1. What was reviewed

The repository at the start of this assignment contains a single empty `README.md`.
**No research documents, product requirements, legal analysis, technology-stack proposal or
architectural decisions were present.** The directive's instruction to "review the proposed
technology stack and research documents" could therefore not be carried out against real inputs.

Consequences:

- This planning set is written from first principles plus publicly available regulatory context.
- Every position that would normally come from your research is recorded as an **assumption (A-n)**
  so it can be confirmed or overturned in review.
- Regulatory facts are cited only to justify *design shape* (e.g. "rates change mid-history, so the
  engine must be period-versioned"). **No rate, threshold or deadline in this document set is
  authoritative**; all must enter the system through the verified-source workflow in
  [06-regulatory-rules-engine-spec.md](06-regulatory-rules-engine-spec.md).

If research documents exist elsewhere, please add them under `docs/research/` and this set will be
reconciled against them before approval.

## 2. Regulatory context relevant to design (to be verified by a Cyprus professional)

| Topic | Design relevance | Status |
|---|---|---|
| Cyprus 2026 tax reform (in force 1 Jan 2026; amending laws published in the Official Gazette 31 Dec 2025): corporate income tax 12.5% → 15%, SDC on dividends 17% → 5%, deemed dividend distribution abolished for post-2026 profits, loss carry-forward 7 years, stamp duty abolished | Proves that rules must be **effective-dated** and that historical periods (FY2025) must still compute under old rules. It is the reference boundary test case for the rules engine. Transitional rules (e.g. pre-2026 profits) need professional reading of the law text. | Secondary sources; verify against the Gazette text |
| VAT: standard and reduced rates, temporary zero-rate on basic goods (reported extended to 31 May 2027) | Rates are time-boxed and product-category specific → VAT rule versions need `valid_from`/`valid_to` and category mappings | Verify with the Tax Department |
| E-invoicing: B2G via Peppol (EN 16931) accepted since 2020; no confirmed domestic B2B mandate as of mid-2026; ViDA requires intra-EU B2B structured e-invoicing and digital reporting from 1 Jul 2030 | Invoice model must be EN 16931-mappable from day one; Peppol integration is an optional adapter, not core | Monitor |
| Statutory financial statements under IFRS as adopted by the EU (Companies Law, Cap. 113) | The chart of accounts and reporting layer must map to IFRS line items | Verify scope (small-company options) |
| Audit: ISA, ICPAC, Cyprus Public Audit Oversight Board | Audit module supports working papers and evidence. The system never issues an opinion. | Confirm |
| GDPR and Cyprus Law 125(I)/2018; AML Law 188(I)/2007 (client due diligence for accounting firms) | Data minimisation, DPA/sub-processor control, retention vs erasure conflicts, KYC records | Confirm with counsel |
| Record retention (tax and VAT records are typically multi-year, commonly cited as 6+ years) | Retention policy must be configurable per record class and jurisdiction, with legal hold | **Verify exact periods** |
| DAC7, DAC8, Pillar Two (QDMTT) | Out of scope for the MVP; the architecture must allow new rule packs | Future |

## 3. Assumptions (please confirm or correct)

| ID | Assumption |
|---|---|
| A-1 | *(superseded by PRD v2)* Primary customers are Cyprus accounting/audit firms (multi-client) and SMEs (single entity). Firms manage many client entities. |
| A-2 | *(superseded by PRD v2: MVP = Phase 1 + Phase 2 FP&A)* The MVP is general ledger + VAT, with corporate tax computation as phase 2. Audit working papers are phase 3. Filing to Tax Department portals is assisted (export/prepare), not automated, in early phases. |
| A-3 | All production data is hosted in the EU (single EU region at launch, plus a DR region in the EU). |
| A-4 | Functional currency is EUR for Cyprus entities. Multi-currency transactions with FX revaluation are needed early (common for Cyprus holding/trading companies). |
| A-5 | UI languages are English and Greek. Statutory outputs may need Greek. |
| A-6 | The team is small (2–6 engineers), so a **modular monolith** is preferred over microservices. The AI service is the one deliberately separate deployable. |
| A-7 | No pre-existing commitment to a cloud vendor or identity provider. |
| A-8 | Commercial SaaS licence, so copyleft (AGPL/SSPL) components are avoided in distributed or network-served core code unless reviewed. |

## 4. Technology stack review

No stack was proposed, so a recommendation follows. The main selection criteria were decimal
correctness, mature migrations and auth, row-level tenant isolation, a hiring pool and licence
safety. Decisions are recorded in [../adr/](../adr/).

| Layer | Recommendation | Why | Rejected alternatives |
|---|---|---|---|
| Database | **PostgreSQL 17** | `NUMERIC` exact decimals, Row-Level Security, deferred constraints, triggers for immutability, `pgvector` for retrieval, mature ops | MySQL (weaker RLS story), document DBs (no relational integrity for ledgers) |
| Backend | **Python 3.13 + Django 5.x + Django REST Framework** (or Django Ninja) | `decimal.Decimal` is native and safe, mature migrations/admin/auth, explicit app modules map to bounded contexts, strong ecosystem for PDF/XML/finance | TypeScript/NestJS (no native decimal; relies on decimal.js discipline everywhere), Java/Kotlin Spring (excellent `BigDecimal`, but slower iteration for a small team; a valid alternative if the team is JVM-native) |
| Background jobs | **Postgres-backed queue** (e.g. Procrastinate) initially; Celery + Redis if throughput requires | One less stateful system; transactional enqueue | — |
| Frontend | **React + TypeScript + Vite**, component library (e.g. Mantine/MUI, MIT-licensed), TanStack Query; money is handled as **strings** end-to-end and formatted only for display | Wide talent pool; no float arithmetic in the client | — |
| Identity | **OIDC provider**: Keycloak (Apache-2.0, self-hosted, EU) *or* a managed EU-resident IdP; MFA (TOTP + WebAuthn/passkeys) | Standards-based, SSO for firms, avoids building password storage | Rolling our own auth |
| Object storage | S3-compatible with SSE-KMS, versioning, **Object Lock (compliance mode)** for evidence | WORM evidence retention | — |
| Secrets & keys | Cloud KMS + secrets manager; envelope encryption per tenant for documents | — | Secrets in env files |
| AI | Isolated **AI Gateway service**; LLM provider reachable only from it, EU-region endpoint, zero-data-retention contract (e.g. Claude via an EU cloud region), with an option to disable AI per tenant | See SAD §7 | Direct LLM calls from the core app |
| Infra | Containers on a managed Kubernetes or ECS-equivalent; Terraform; GitHub Actions CI | — | — |
| Observability | OpenTelemetry → EU-hosted backend; structured logs with a **PII redaction layer** | — | — |

Licensing watch-list: verify licences for PDF generation (avoid AGPL iText; prefer WeasyPrint/BSD,
ReportLab/BSD), XBRL tooling (Arelle is Apache-2.0), OCR (Tesseract Apache-2.0), and any embedded
tax content (official texts are generally reusable, while commercial commentary is not).

## 5. Open questions for the product owner

1. Do research/legal documents exist? Please share them.
2. Is the first paying customer an accounting firm or an SME? This changes the Milestone 1 UX.
3. Which statutory outputs are must-haves for launch: VAT return (VAT4) preparation, IR4 corporate return, IFRS financial statements, or VIES recapitulative statements?
4. Is a Cyprus-qualified tax advisor/auditor available to own rule-pack verification and sign test cases? (**Required** by the rules-engine design.)
5. Do you have cloud vendor, IdP, or LLM provider preferences or contracts?
6. What import sources are needed in phase 1: bank statements (CSV/CAMT.053), legacy software exports (which products?), or Excel?
7. What are the target SLA/RPO/RTO and expected tenant/entity counts at year 1?
