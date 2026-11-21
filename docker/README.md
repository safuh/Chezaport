# Container assets

- `Dockerfile`: locked, non-root production image.
- `compose.yml`: local PostgreSQL + API development stack.
- `compose.staging.yml`: staging API using an externally managed PostgreSQL DB.
- `compose.production.yml`: production API using an externally managed PostgreSQL DB.
- `scripts/docker-smoke.sh`: disposable local PostgreSQL/Compose smoke test.
- `scripts/docker-staging.sh`: build, migrate, deploy, and readiness-check staging.
- `scripts/docker-production.sh`: build, migrate, deploy, and readiness-check production.

Staging and production require a PostgreSQL asyncpg URL, force debug mode off,
and bind the API to loopback. Public HTTPS must be terminated by a separately
managed reverse proxy or ingress. Credentials must be supplied through protected
deployment environment variables or a secret manager; never bake secrets into
the image or commit them to the repository.

See [the deployment runbook](../docs/DEPLOYMENT_RUNBOOK.md) for preflight,
release, rollback, and infrastructure requirements.
