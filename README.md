# Chezaport

Chezaport is a backend-first football information platform built on
[FastApiBackbone](https://github.com/safuh/FastApiBackbone). The MVP is a modular
monolith with a provider-neutral sports domain, ingestion boundary, public read
API, and deterministic football analytics.

**Stack:** Python 3.11+ · FastAPI · Pydantic v2 · SQLAlchemy 2.x · Alembic ·
SQLite (local) · PostgreSQL (staging/production) · Docker Compose.

## MVP scope

- Canonical sports catalogue: sports, countries, competitions, seasons, teams,
  players, venues, memberships, fixtures, and provider ID mappings.
- Provider-neutral normalized schemas, capability-based provider routing,
  bounded retry policy, and transaction-safe/idempotent ingestion services.
- Versioned read API for sports, competitions, fixtures, standings, team form,
  and head-to-head results.
- Optional Argon2/JWT identity composition with registration, login, refresh
  rotation, logout, and refresh-token revocation.
- Health/readiness endpoints, correlation IDs, structured logging, migrations,
  and container deployment assets.

The MVP is API/backend only. It does not include a web/mobile frontend, AI
features, Redis, message brokers, or microservices.

## Quick start

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), and optionally
Podman/Docker with Compose.

```bash
uv sync --locked --extra dev
cp .env.example .env
make check
make migrate-up
uv run python -m chezaport.sports.seed
make run
```

- API discovery: http://127.0.0.1:8000/api/v1/
- Swagger UI: http://127.0.0.1:8000/docs
- Liveness: http://127.0.0.1:8000/api/health/live
- Readiness: http://127.0.0.1:8000/api/health/ready

SQLite is the default local database. Alembic migrations are required before
using persistent data. The default sports seed is idempotent.

## Public API

All product endpoints are under `/api/v1`.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/sports` | Active sports |
| GET | `/competitions` | Competitions, optionally filtered by `sport_id` |
| GET | `/fixtures` | Filtered fixtures with bounded pagination |
| GET | `/competitions/{competition_id}/standings?season_id=...` | 3-1-0 league table |
| GET | `/teams/{team_id}/form?competition_id=...&season_id=...` | Recent completed results |
| GET | `/teams/head-to-head?... ` | Completed meetings between two teams |

Standings use points, goal difference, goals scored, then team name as tie-break
order. Only finished fixtures with both scores are counted. Fixture timestamps
must be timezone-aware at ingestion boundaries.

## Authentication

Authentication is optional and must be explicitly composed by the consuming
application. The API returns 503 for auth endpoints until an
`AuthenticationApplication` factory is supplied. Do not treat the presence of
the auth module as an enabled user-management system. See
[security guidance](docs/SECURITY.md).

## Data providers

The domain and ingestion services are provider-neutral. A read-only
football-data.org v4 adapter is implemented with normalized competition, season,
team, and fixture mapping, typed rate-limit/error handling, and mocked HTTP
contract tests. The adapter is not enabled by default; configure
`FOOTBALL_DATA_API_TOKEN` and `FOOTBALL_DATA_COMPETITION_CODES` in a protected
runtime environment to register its competition routes. No token is needed for
local development or CI. After verifying the provider's terms for the intended
use, run a one-shot, idempotent local sync with:

```bash
uv run python -m chezaport.sports.sync --competition PL --since 2026-08-01
```

The command syncs the configured competition catalogue, seasons, teams, and
fixtures in one transaction; it aborts rather than committing partial ingestion
if a record fails. The provider documents a free-plan limit of 10 calls per
minute and restricted competition/resource coverage; check the current
[API quickstart](https://www.football-data.org/documentation/quickstart) and
[API policies](https://docs.football-data.org/general/v4/policies.html) before
scheduling synchronization. Public display, attribution, caching, and
redistribution rights must be confirmed for the intended use before production
publication. Provider credentials belong in protected runtime environment
variables, never in Git or chat. See the provider decisions in `docs/decisions/`.

## Local PostgreSQL integration

The Compose development stack runs PostgreSQL internally and does not bind
host port 5432:

```bash
make docker-up
docker compose -f docker/compose.yml exec -T api alembic upgrade head
docker compose -f docker/compose.yml exec -T api python -m chezaport.sports.seed
make docker-down
```

The disposable end-to-end smoke test builds the image, starts PostgreSQL and the
API, checks liveness/readiness, applies migrations, and removes its test volume:

```bash
make docker-test
```

## Staging deployment

Staging requires a dedicated PostgreSQL database and protected deployment
environment variables. It deliberately uses production-like validation, JSON
logs, and no debug mode.

```bash
export DATABASE_URL='postgresql+asyncpg://USER:PASSWORD@HOST:5432/chezaport_staging'
export APP_PORT=8001
export CORS_ORIGINS='["https://staging.example.com"]'
make docker-staging
```

The service binds to loopback only. Put it behind a TLS-terminating reverse
proxy or managed ingress. Use a separate staging database; never point staging
at production data.

## Production deployment

```bash
export DATABASE_URL='postgresql+asyncpg://USER:PASSWORD@HOST:5432/chezaport'
export APP_PORT=8000
export CORS_ORIGINS='["https://app.example.com"]'
make docker-prod
```

The production script validates Compose configuration, builds the locked
non-root image, runs Alembic as a one-shot migration, starts the API, and waits
for readiness. The container is bound to loopback so a separately managed TLS
proxy/ingress can expose HTTPS. Store secrets in the host's secret manager or
deployment environment, not in a committed file.

Before public production traffic, configure TLS, strict CORS, database network
allowlists, automated encrypted backups and restore drills, monitoring/alerting,
edge rate limiting, and an operational rollback procedure. Database migrations
must be reviewed for backward compatibility before rolling out multiple API
replicas.

## Quality gates

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

PostgreSQL integration tests run when `TEST_DATABASE_URL` is configured. The
local SQLite suite does not replace PostgreSQL migration/transaction testing.
