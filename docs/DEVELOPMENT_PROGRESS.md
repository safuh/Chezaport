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

### 2026-11-10 — provider integration, ingestion, and validation

- Added normalized Pydantic schemas for competitions, seasons, teams, and fixtures, plus the async `SportsDataProvider` protocol.
- Added typed provider errors, external-ID resolution, and transaction-safe ingestion for competitions, teams, seasons, and fixtures.
- Added an idempotent canonical football bootstrap command: `uv run python -m chezaport.sports.seed`.
- Tightened fixture ingestion so the competition and participating teams must resolve consistently to the same sport.
- Added bounded asynchronous retry for temporary provider failures and rate limits, including Retry-After handling. Retry tests inject sleep and make no network requests.
- Confirmed the English Premier League (EPL, canonical code `PL`) as the initial pilot. football-data.org is the approved initial provider, but its authenticated adapter remains paused until local credential configuration.
- Documented free-tier limits: delayed data, 10 requests/minute, visible attribution, and no free live scores/deeper match statistics. Data-use and redistribution rights still require review before production use.
- Added explicit provider routing and documented that the registry returns candidates rather than performing automatic failover.
- Added explicit `ProviderCapabilities` declarations for canonical competition codes and resource families (competitions, seasons, teams, fixtures). The registry can now filter ordered candidates by exact resource support and rejects requests when no candidate declares coverage.
- Added deterministic capability and resource-routing tests. This preparation is provider-independent: it uses no API token, network request, Redis, or paid dependency.
- ADRs 0005 and 0006 document provider routing and capability declarations.
- CI was last confirmed successful on run [#33](https://github.com/safuh/Chezaport/actions/runs/42878093037), before this capability increment. The new changes still require CI validation.
