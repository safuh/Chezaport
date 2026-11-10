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
| M0 | Repository baseline and progress tracking | In progress | Branch, issue tracker, constraints, and development log established |
| M1 | API and sports domain foundation | Not started | Versioned API, domain package boundaries, tests, and documented conventions |
| M2 | Core sports entities | Not started | Sport, country, competition, season, team, player, venue, fixture models and migrations |
| M3 | Provider-neutral integration | Not started | Provider contracts, normalized schemas, external-ID mapping, and adapter tests |
| M4 | Free-first data ingestion | Not started | Idempotent import/sync commands, retry policy, rate-limit handling, and no Redis/broker dependency |
| M5 | Sports analytics | Not started | Standings, form, head-to-head, and match statistics with deterministic tests |
| M6 | Public API and frontend readiness | Not started | Documented API endpoints, pagination/filtering, and stable response schemas |
| M7 | Production hardening | Not started | Security review, observability, deployment guide, backups, and performance checks |

## Progress log

### 2026-11-10

- Created working branch `feature/sports-platform-foundation` from `main`.
- Opened [GitHub issue #1](https://github.com/safuh/Chezaport/issues/1) as the milestone tracker.
- Confirmed that Redis is excluded from the architecture.
- Confirmed a free-first policy: no paid API or infrastructure dependency in the initial development path.
- Started the API versioning foundation. Existing routes will remain available while new product endpoints are added under `/api/v1`.

## Progress update procedure

At the end of each implementation session, update this file and GitHub issue #1 with completed work, test results, blockers, and the next concrete task. A milestone is complete only when its exit criteria and tests pass.
