# ADR-0006: Python/Django + PostgreSQL + React/TypeScript
Status: **Accepted** · Date: 2026-11-03 (accepted by product owner 2026-11-03)
## Context
No stack was proposed in the inputs. Needs: native decimal, mature migrations/auth, RLS-capable DB, hiring pool, permissive licences.
## Decision
Python 3.13, Django 5.x (+ DRF or Django Ninja), PostgreSQL 17, a Postgres-backed job queue, React + TypeScript + Vite, an OIDC IdP (Keycloak or managed EU IdP), S3-compatible storage with Object Lock, Terraform, GitHub Actions.
## Consequences
+ `decimal.Decimal` native; fast iteration; strong ecosystem (defusedxml, WeasyPrint, Arelle). − Python CPU performance is lower (mitigated with DB aggregation and snapshots).
## Alternatives considered
Kotlin/Spring (strong option if the team is JVM-native); TypeScript/NestJS (no native decimal type).
