# Deployment runbook

This runbook covers the supported container path. It does not provision a cloud
account, managed PostgreSQL instance, DNS, TLS certificate, or secret manager.

## Environments

| Environment | Database | Runtime profile | Host bind |
| --- | --- | --- | --- |
| Local | SQLite or Compose PostgreSQL | `development` | `127.0.0.1:8000` |
| Staging | Dedicated managed PostgreSQL | `staging` | `127.0.0.1:8001` by default |
| Production | Managed PostgreSQL | `production` | `127.0.0.1:8000` by default |

Staging and production reject SQLite URLs, require debug mode off, and force
JSON logging. They must use different database instances and credentials.

## Release preflight

1. Review the diff and migration scripts.
2. Run `uv sync --locked --extra dev`.
3. Run `uv run ruff format --check .`, `uv run ruff check .`,
   `uv run mypy src`, and `uv run pytest`.
4. Run the PostgreSQL integration suite against a disposable PostgreSQL database
   by setting `TEST_DATABASE_URL`.
5. Run `make docker-test` on a working container host.
6. Build and scan the exact image intended for release.
7. Confirm the release commit, database backup, restore point, and rollback plan.

## Staging

Use a dedicated staging PostgreSQL database and deployment secrets. Set:

- `DATABASE_URL`: async PostgreSQL URL for staging.
- `APP_PORT`: host port, default 8001.
- `CORS_ORIGINS`: JSON array of staging frontend origins.
- `APP_VERSION`: immutable release identifier.

Run `make docker-staging`. The script validates Compose configuration, builds
the image, applies migrations once, starts the API, and waits for database-backed
readiness. Verify `/api/health/live`, `/api/health/ready`, `/docs`, and
representative read endpoints. Inspect logs for errors and confirm no secrets
are emitted.

## Production

Take and verify a database backup before applying migrations. Set the same
variables using production-specific values, then run `make docker-prod`.
Place a managed TLS reverse proxy or ingress in front of the loopback-bound API.
Do not expose the container's HTTP port directly to the public internet.

Migrations run as a one-shot task before the API rollout. For schema changes
that are not backward-compatible, use an expand/migrate/contract sequence:
deploy additive schema, deploy compatible code, backfill, then remove obsolete
schema only in a later release.

## Rollback and recovery

- Roll back the application image to the previous immutable release if the API
  fails its smoke checks.
- Do not automatically downgrade the database after a failed rollout.
- Restore the database only when the migration or data operation requires it,
  using the verified backup and documented recovery point.
- Preserve logs and migration output for incident analysis.
- Re-run readiness and read-only API smoke checks after recovery.

## Operational controls required before public launch

- HTTPS/TLS and strict CORS allowlists.
- Secret manager or protected runtime environment; high-entropy JWT keys for
  applications that enable the optional authentication composition.
- PostgreSQL network restrictions, least-privilege database user, encrypted
  backups, retention policy, and tested restore procedure.
- Reverse-proxy rate limiting and request-size/time limits.
- Centralized logs, metrics, uptime alerts, database monitoring, and incident
  ownership.
- Provider data licensing, attribution, freshness disclosures, and usage limits
  confirmed for every enabled competition.

## Current boundaries

The repository supplies application containers, Compose staging/production
profiles, migrations, health checks, and a deployment script. A real hosted
staging or production environment remains unprovisioned until an infrastructure
provider, domain, managed database, and secret-management mechanism are selected
and credentials are configured outside the repository.
