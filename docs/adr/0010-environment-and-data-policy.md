# ADR-0010: Environment and data policy (synthetic dev/staging, owner-only pilot)
Status: **Accepted** · Date: 2026-11-03 (accepted by product owner 2026-11-03)
## Context
The product owner wants to use the platform personally during development with realistic data; real confidential client data must not enter unapproved environments or AI services.
## Decision
`dev` and `staging` use synthetic data only (seeded generators, incl. a parameterised profile generator). A separate `pilot` environment with production-grade controls hosts only the owner's own personal/business data until Gate G; it is created and deployed only with explicit owner approval. No data path from pilot to dev/staging. AI provider allow-lists are enforced per environment in the AI Gateway config; AI is disabled in pilot by default.
## Consequences
+ Real-world usefulness testing without exposing client data. − An extra environment to operate; the owner's own business data may still include third-party personal data and is treated as confidential.
