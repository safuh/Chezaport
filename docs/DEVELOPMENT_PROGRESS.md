# Chezaport Development Progress

## Product direction

Chezaport is being developed into a sports information and analysis platform. The initial product scope is football-first, while the domain model and provider interfaces must remain extensible to other sports.

## Engineering constraints

- **No Redis.** Do not add Redis, Redis-backed caches, queues, or session storage.
- **Free-first development.** Prefer free/open-source libraries and local development. Any hosted free tier or sports-data provider must have its quotas, attribution rules, freshness limits, and commercial-use restrictions documented before adoption.
- **No paid dependency.** The initial development workflow must not require a paid API, paid database, or paid hosting plan.
- **Modular monolith.** Keep domain logic inside Chezaport; do not introduce microservices prematurely.
- **Compatibility.** Preserve existing authentication, health, database, and application-factory behavior unless a tested migration is explicitly planned.

## Current baseline

- Repository: [safuh/Chezaport](https://github.com/safuh/Chezaport)
- Base branch: `main`
- Working branch: `feature/sports-platform-foundation`
- Existing stack: FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, SQLite for local development, PostgreSQL support, and `uv`.
- Background execution: begin with explicit CLI commands and simple scheduled Python processes. Select a lightweight scheduler only when recurring jobs are needed; no broker is required for the initial design.

## Milestones

| ID | Milestone | Status | Exit criteria |
|---|---|---|---|
| M0 | Repository baseline and progress tracking | Complete | Branch, issue tracker, constraints, and development log established |
| M1 | API and sports domain foundation | Complete | Versioned API, domain package boundaries, tests, and documented conventions |
| M2 | Core sports entities | Complete | Sport, country, competition, season, team, player, venue, fixture models and migrations |
| M3 | Provider-neutral integration | Complete | Provider contracts, normalized schemas, external-ID mapping, and adapter tests |
| M4 | Free-first data ingestion | In progress | Provider adapter, idempotent import/sync commands, retry policy, rate-limit handling, and no Redis/broker dependency |
| M5 | Sports analytics | Not started | Standings, form, head-to-head, and match statistics with deterministic tests |
| M6 | Public API and frontend readiness | Not started | Documented API endpoints, pagination/filtering, and stable response schemas |
| M7 | Production hardening | Not started | Security review, observability, deployment guide, backups, and performance checks |

## Progress log

### 2026-11-10

- Created working branch `feature/sports-platform-foundation` from `main`.
- Opened [GitHub issue #1](https://github.com/safuh/Chezaport/issues/1) as the milestone tracker.
- Confirmed that Redis is excluded from the architecture.
- Confirmed a free-first policy: no paid API or infrastructure dependency in the initial development path.
- Added an explicit `/api/v1` router while preserving existing health and authentication routes at their current paths.
- Established the `sports` and `sports.domain` package boundaries.
- Added normalized `SportCode` and `FixtureStatus` domain enums so provider-specific status values can be mapped at integration boundaries.

### 2026-11-10 — continued implementation

- M1 implementation: added the versioned API discovery endpoint and a corresponding test. Validation is still pending.
- M2 implementation started: added nine core sports tables and Alembic migration `0004_sports_core`.
- Player-team history is represented by time-bounded team memberships rather than a single mutable current-team field.
- Added SQLite-focused tests for metadata registration, table creation, and the full Alembic migration chain.
- Added database constraints for fixture scores and statuses, distinct home/away teams, venue capacity, and date ordering.
- Registered sports models with Alembic metadata.
- Validation remains pending: remote repository edits were made, but the project test suite and migration chain have not yet been executed in a local checkout or CI. M1 is implemented but unverified; M2 remains in progress.

## Progress update procedure

At the end of each implementation session, update this file and GitHub issue #1 with completed work, test results, blockers, and the next concrete task. A milestone is complete only when its exit criteria and tests pass.

### 2026-11-10 — provider integration foundation

- Added normalized Pydantic schemas for provider competitions, seasons, teams, and fixtures. Provider-specific extra fields are ignored at the boundary rather than entering the core domain.
- Added the async `SportsDataProvider` protocol so vendor adapters share one contract.
- Added typed provider exceptions for configuration, temporary unavailability, and rate-limit responses, including optional retry-after metadata.
- Added the provider-neutral `external_id_mappings` table and Alembic revision `0005_external_id_mappings`. Provider IDs are mapped to canonical entities without adding vendor columns to the sports tables.
- Added schema tests for whitespace normalization, timezone-aware fixture kickoff, distinct home/away teams, and valid season date ranges.
- Added a free GitHub Actions CI workflow on pushes to `main`/`feature/**` and pull requests targeting `main`. It runs lint, mypy, and pytest across Python 3.11–3.13.
- Validation is still pending: the workflow has been added but its run result has not yet been inspected, and the suite has not been run locally. M3 remains in progress until adapter contract tests and validation pass.

### 2026-11-10 — external ID resolution service

- Added a canonical entity-type enum for provider mapping targets.
- Added `ExternalIDResolver`, which resolves provider IDs and registers mappings idempotently inside the caller's SQLAlchemy transaction. It never creates sessions or commits.
- Added conflict detection for attempts to reassign an existing provider ID or attach a second provider ID to the same canonical entity.
- Added async SQLite tests for resolution, idempotent registration, and both conflict cases.
- The resolver relies on database unique constraints as the final concurrency guard; ingestion callers must handle an `IntegrityError` from concurrent duplicate registration and retry their transaction.
- Validation remains pending because no local checkout or completed CI result has been inspected.

### 2026-11-10 — first ingestion service increment

- Added `SportsIngestionService` for explicit provider-neutral competition and team upserts. It resolves provider IDs, reuses canonical records by sport/slug where possible, and registers mappings.
- Added per-record result objects and batch counts for created, updated, unchanged, and failed records.
- Each record is isolated in a database savepoint: invalid records are reported without aborting successful records in the same batch. The service never commits; the caller owns the outer transaction.
- Canonical sport records must be seeded before importing records for that sport. If a provider supplies a country code, that country must also exist in the canonical country table; this avoids silently creating incomplete country records.
- Added tests for idempotent competition imports, team updates, per-record failure isolation, and missing canonical country handling.
- M4 is now in progress. The provider adapter, retry/backoff policy, ingestion CLI, and end-to-end validation remain outstanding.
- Validation remains pending: these changes were committed remotely; no local test execution or confirmed CI result is available yet.

### 2026-11-10 — lint correction and expanded ingestion

- Fixed the Ruff E501 violation in migration `0004_sports_core.py` by wrapping the two team-membership index declarations across multiple lines. The reported line was a static lint finding; it was not evidence that the database failed while creating the index.
- Extended the ingestion service to import seasons and fixtures after their referenced competitions and teams have been mapped.
- Added dependency resolution checks so a fixture cannot be ingested against missing provider mappings or a season belonging to another competition.
- Normalized fixture kickoff timestamps to UTC before persistence and compare timestamps consistently when SQLite returns timezone-naive values.
- Added tests for the competition-to-season-to-teams-to-fixture import sequence, idempotent fixture replay, and unresolved fixture dependencies.
- CI must be rerun on the branch to verify the Ruff correction and the expanded test suite. No passing result is claimed until the workflow completes successfully.


### 2026-11-10 — canonical sports bootstrap and fixture integrity

- Added an idempotent bootstrap service for built-in canonical sports and a CLI entry point: `uv run python -m chezaport.sports.seed`.
- The bootstrap seeds association football only (the currently supported `SportCode`), preserves existing records, participates in the caller-owned transaction, and does not create country records or invent a country catalogue.
- Added tests for first-time creation, repeat execution, and preserving an existing canonical sport.
- Tightened fixture ingestion: the competition must resolve to a canonical record, and both participating teams must belong to the same sport as that competition. This closes a cross-sport data-integrity gap not enforced by the current relational schema.
- The CLI assumes migrations have already been applied. It uses the existing configured database URL and shared engine/session infrastructure; no Redis, task broker, paid service, or new dependency was introduced.
- Validation is still pending until Ruff, mypy, pytest, and the branch CI workflow have actually completed successfully.


### 2026-11-10 — CI validation checkpoint

- GitHub Actions run [#21](https://github.com/safuh/Chezaport/actions/runs/42867249463) completed successfully for commit `934894cfbd3ce7eb17ac3a7847906b55ffb3ef6d`.
- Ruff lint, mypy type checking, and pytest all passed on Python 3.11, 3.12, and 3.13.
- M1, M2, and M3 are marked complete based on the implemented scope and passing CI. M4 remains in progress: a real provider adapter, retry/rate-limit policy, ingestion CLI, and repeatable scheduled sync are still outstanding.


### 2026-11-10 — provider retry foundation and European pilot decision

- Added a bounded asynchronous retry helper for transient provider-unavailable and rate-limit failures. It uses exponential backoff and honors provider-supplied Retry-After values; configuration/authentication errors are not retried.
- Added deterministic tests for retry success, Retry-After precedence, non-retryable configuration errors, attempt exhaustion, and invalid configuration. These tests use an injected sleep function and do not make network requests.
- Researched football-data.org as the European pilot candidate. The free tier currently lists 12 competitions, including Bundesliga (BL1), with delayed scores and a 10 requests/minute limit. Authenticated data access requires a registered API token and visible attribution.
- Added ADR 0004 documenting the candidate, limitations, credential handling, attribution, and unresolved data-use/redistribution terms. The provider adapter is intentionally paused pending owner approval and clarification of intended usage rights; no credential is committed or requested in chat.
- CI must be checked by the project owner before the next code push. No local Ruff, mypy, or pytest execution is claimed for this increment.
