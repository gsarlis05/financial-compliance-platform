# ADR-0005: AI as a non-authoritative, read-only, isolated service
Status: **Accepted** · Date: 2026-11-03 (accepted by product owner 2026-11-03)
## Context
LLMs can hallucinate, can be prompt-injected by documents, and are third-party processors of confidential data.
## Decision
AI never computes authoritative figures, never writes to ledger, filings or rules, and never submits or opines. The core assembles context under the user's permissions; the gateway wraps documents as untrusted data, exposes only read-only retrieval over allowed references and the verified source library, and validates outputs (citations must resolve; numbers are checked against engine traces). Outputs are drafts requiring human acceptance. AI is off by default per tenant, uses an EU endpoint with zero data retention, and applies data-class redaction.
## Consequences
+ Worst case of a successful injection is a bad draft that is caught in review. − Less "automation magic"; validator maintenance cost.
