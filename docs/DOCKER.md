# Docker and container deployment

## Image contract

The production image uses the committed `uv.lock` file and
`uv sync --locked --no-dev --no-editable`. A stale lockfile fails the build.
The runtime image excludes development dependencies and runs as the non-root
`app` user. No secrets are baked into image layers.

## Local PostgreSQL development

```bash
make docker-up
docker compose -f docker/compose.yml exec -T api alembic upgrade head
docker compose -f docker/compose.yml exec -T api python -m chezaport.sports.seed
make docker-down
```

The database is internal to the Compose network and does not bind host port
5432. The local stack uses disposable development credentials.

Run the complete container smoke test with:

```bash
make docker-test
```

It builds the image, starts PostgreSQL and the API, checks liveness/readiness,
runs migrations, and removes the test stack and volume on exit.

## Staging

Staging requires an externally managed PostgreSQL database and a protected
runtime environment:

```bash
export DATABASE_URL='postgresql+asyncpg://USER:PASSWORD@HOST:5432/STAGING_DB'
export APP_PORT=8001
export CORS_ORIGINS='["https://staging.example.com"]'
make docker-staging
```

The staging profile forces `ENVIRONMENT=staging`, debug off, and JSON logs. It
requires PostgreSQL. The API binds to `127.0.0.1` and must be placed behind a
TLS reverse proxy or managed ingress. Use a dedicated staging database.

## Production

```bash
export DATABASE_URL='postgresql+asyncpg://USER:PASSWORD@HOST:5432/PRODUCTION_DB'
export APP_PORT=8000
export CORS_ORIGINS='["https://app.example.com"]'
make docker-prod
```

The production profile requires PostgreSQL, disables debug mode, and forces
JSON logs. The deployment script validates Compose configuration, builds the
locked image, applies Alembic migrations as a one-shot operation, starts the API,
and waits for database-backed readiness.

Both staging and production bind the application to loopback. A separately
managed TLS reverse proxy/ingress must provide public HTTPS. Do not expose the
container HTTP port directly to the public internet.

## Migration contract

Migrations are not run by every API process. Deployments run
`alembic upgrade head` once before starting the new API version. Review
backward compatibility and take a verified database backup before production
migrations. Do not automatically downgrade a production database after a failed
rollout.

## Infrastructure responsibilities

The repository does not provision cloud infrastructure, managed databases,
DNS, certificates, secret managers, or backup systems. Before public launch,
configure TLS, strict CORS, database network allowlists, encrypted backups and
restore drills, monitoring/alerting, edge rate limiting, and a rollback plan.
See [the deployment runbook](DEPLOYMENT_RUNBOOK.md).
