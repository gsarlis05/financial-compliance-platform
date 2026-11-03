# ADR-0001: Modular monolith with an isolated AI gateway
Status: Proposed · Date: 2026-11-03
## Context
A small team needs strong consistency across ledger, tax and audit data, and fast iteration. AI calls carry data-exfiltration and prompt-injection risk.
## Decision
One core deployable with enforced module boundaries (import-linter contracts, `api.py` per module, domain events via a transactional outbox). The AI Gateway is a separate service with no DB credentials and the sole egress to LLM providers.
## Consequences
+ ACID transactions across posting, balances and audit; simpler ops. + AI blast radius contained.
− Discipline is required to keep boundaries; scaling is per-process rather than per-module.
## Alternatives considered
Microservices (premature, distributed-transaction complexity for ledgers); AI inside the monolith (weaker isolation).
