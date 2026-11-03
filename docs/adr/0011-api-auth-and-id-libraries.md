# ADR-0011: Django Ninja API, Authlib OIDC (BFF sessions), UUIDv7 identifiers
Status: **Accepted** · Date: 2026-11-03 (within the approved Milestone 1 go-ahead; open to revision in review)

## Context
ADR-0006 left "DRF or Django Ninja" open. Milestone 1 needs a typed API with generated OpenAPI,
an OIDC client for the backend-for-frontend login (doc 04 §2), and time-ordered identifiers (doc 03).

## Decision
- **Django Ninja** for the HTTP API: Pydantic v2 schemas give strict typing (mypy-friendly), string
  serialisation of `Decimal`, and OpenAPI generation. Permissions are declared per operation.
- **Authlib** (Django client) for OIDC Authorization Code with PKCE S256, nonce and state. ID tokens
  are validated against the IdP's JWKS. Tokens never reach the browser; the browser holds only a Django
  session cookie (`__Host-` prefix, HttpOnly, Secure, SameSite=Lax).
- **UUIDv7** primary keys (RFC 9562) generated in `fcp.core.ids` (Python 3.13 has no built-in uuid7).

## Consequences
+ Typed request/response models; one source for the OpenAPI spec; a well-reviewed OIDC implementation.
− Ninja has a smaller ecosystem than DRF. Permission handling is our own thin layer, which is fine
  because authorization is centralised in `tenancy.authz` anyway.

## Alternatives considered
DRF (weaker typing, more implicit behaviour); hand-written OIDC client (avoidable security risk);
mozilla-django-oidc (less flexible PKCE and claim handling).
