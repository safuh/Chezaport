# MVP acceptance tracker

A checkbox is marked only after the criterion is implemented and verified. This
tracker is intentionally stricter than a feature checklist.

## Product boundary

**Included:** Python/FastAPI backend, Pydantic v2, SQLAlchemy 2.x, Alembic,
SQLite local development, PostgreSQL staging/production, provider-neutral sports
domain and ingestion, football read API/analytics, optional identity, Docker
image, and Compose deployment scripts.

**Excluded from this MVP:** web/mobile frontend, AI features, PydanticAI, Flutter,
Redis, message brokers, microservices, and Kubernetes. A Kubernetes deployment
can be added later if the selected hosting environment requires it.

## M1 — Application foundation

**Status: complete and verified.**

- [x] Python src-layout package and application factory.
- [x] Development, test, staging, and production settings profiles.
- [x] FastAPI exception handling and stable error envelope.
- [x] Request correlation IDs and structured logging.
- [x] Explicit CORS configuration.
- [x] Liveness and database-backed readiness endpoints.
- [x] Deterministic application lifespan and engine disposal.

## M2 — Persistence and migrations

**Status: implemented; SQLite verified, PostgreSQL release gate pending.**

- [x] Async SQLAlchemy engine and session factory.
- [x] SQLite/aiosqlite and PostgreSQL/asyncpg drivers.
- [x] Transaction-scoped session helper and Unit of Work.
- [x] Async Alembic environment.
- [x] Versioned identity and sports migrations.
- [x] SQLite schema creation and migration tests.
- [ ] PostgreSQL migration upgrade/downgrade verified in the current release run.

## M3 — Optional identity and JWT

**Status: implemented and covered by automated tests; not enabled by default.**

- [x] Argon2 password hashing and generic invalid-credential behavior.
- [x] Signed access/refresh JWT validation and expiration.
- [x] Persistent refresh-token rotation, replay rejection, and revocation.
- [x] Registration, login, refresh, and logout HTTP endpoints.
- [x] Authentication audit events and SQLAlchemy composition helper.
- [ ] Product-specific roles/scopes and rate limiting remain outside this MVP.

Authentication endpoints intentionally return 503 until the consumer composes
an authentication application with real signing secrets and persistence.

## M4 — Sports domain and ingestion foundation

**Status: provider-neutral foundation implemented; live provider integration pending.**

- [x] Sport, country, venue, competition, season, team, player, membership,
  fixture, and external-ID mapping models.
- [x] Normalized Pydantic provider schemas and async provider protocol.
- [x] Provider capability declarations and competition-aware routing.
- [x] External-ID resolution and transaction-safe, idempotent ingestion.
- [x] Bounded retry policy with Retry-After handling.
- [x] Canonical football bootstrap command.
- [ ] A live provider adapter and scheduled synchronization workflow.
- [ ] Owner approval, credentials, quota/freshness verification, attribution,
  and redistribution rights for the chosen competition data provider.

The EPL/football-data.org pilot is not enabled until its use and redistribution
terms are confirmed. CI must remain network- and credential-independent.

## M5 — Public sports API and analytics

**Status: implemented; automated contract tests added.**

- [x] Versioned API discovery endpoint.
- [x] Active sports and competition catalogue endpoints.
- [x] Fixture filters and bounded offset pagination.
- [x] Deterministic 3-1-0 standings from completed fixtures.
- [x] Team recent form and head-to-head summaries.
- [x] Analytics regression tests for scoring, form ordering, and unfinished
  fixture exclusion.
- [ ] Production query-plan review and larger-dataset performance benchmark.

The current API is read-only. Canonical data enters through the ingestion
service; authenticated operational write workflows are a later increment.

## M6 — Release verification

**Status: in progress.**

- [x] Ruff lint and repository formatting.
- [x] Mypy application type check.
- [x] SQLite unit/integration tests.
- [x] API contract tests for catalogue, fixtures, standings, and form.
- [ ] Full suite rerun after the latest changes.
- [ ] PostgreSQL integration and migration upgrade/downgrade run.
- [ ] Container build and end-to-end Compose smoke test.
- [ ] Dependency audit, secret scan, package build, and release CI verification.

## M7 — Staging and production operations

**Status: deployment assets implemented; real environment not provisioned.**

- [x] Locked, non-root production Docker image.
- [x] PostgreSQL-backed local Compose development stack.
- [x] Separate staging and production settings validation.
- [x] Staging/production Compose definitions with loopback-only binds.
- [x] Explicit one-shot migrations before API rollout.
- [x] Readiness-based deployment scripts and runbook.
- [ ] Verify Compose build/smoke on a functioning container runtime.
- [ ] Provision a staging host, managed PostgreSQL database, domain, TLS, and
  deployment secrets.
- [ ] Verify staging smoke tests and migration behavior against PostgreSQL.
- [ ] Provision production infrastructure, encrypted backups, restore drills,
  monitoring, edge rate limiting, and an operational rollback procedure.

## Release definition

The MVP is not declared production-ready merely because the application starts
locally. Release requires all M6 gates to pass on the release commit, successful
PostgreSQL migration and container smoke tests, and completed M7 infrastructure
controls. A real hosted deployment cannot be performed until an infrastructure
provider, database, domain, TLS/ingress, and protected secrets are provisioned.

## Change control

Keep the initial release backend-focused. New features must not silently add
paid provider dependencies, Redis, AI, frontend/mobile clients, or distributed
services. Provider selection and public data rights require explicit review.
