# Render production deployment

ChezaPort's first release is a public, read-only sports information product.
Visitors can browse the dashboard and public API without registering or signing
in. Do not configure `JWT_SECRET_KEY` for this release. The optional identity
primitives remain dormant and are not a visitor-access requirement.

## Topology

The root `render.yaml` defines three resources in Frankfurt:

- `chezaport-web`: Docker web service serving the dashboard and versioned API.
- `chezaport-sync`: isolated background worker that refreshes provider data.
- `chezaport-db`: managed PostgreSQL 17 database.

Both services deploy only after configured Git checks pass. The web service applies Alembic migrations in its pre-deploy release step and
uses `/api/health/ready` as its HTTP health check. The worker shares the
database and provider token but does not receive public inbound traffic.
The database URL is normalized to SQLAlchemy's `postgresql+asyncpg` driver by
application configuration.

The blueprint starts with a 1 CPU / 2 GB web service, a 0.5 CPU / 512 MB
background worker, and a 0.5 CPU / 1 GB managed PostgreSQL plan (`0.5c-1g`)
with 15 GB of storage. The database IP allowlist is empty so the database is
reachable only through Render's private network. These are paid plans, not
ephemeral/free instances. Review current regional availability and pricing in
the Render dashboard before provisioning.

## First deployment

1. Review the branch and make sure the intended release commit is the branch
   containing `render.yaml`. Do not deploy an unreviewed feature branch as the
   permanent production release.
2. In Render, create a new Blueprint from this GitHub repository and select the
   reviewed release branch.
3. Review the three proposed resources and their region/plan before applying.
4. Enter the football-data.org token when prompted for
   `FOOTBALL_DATA_API_TOKEN`. Keep it in the service's secret environment only;
   never commit it or copy it into browser code. If provider data is not yet
   approved for public display, leave the integration unconfigured and do not
   start the sync worker.
5. Confirm the database resource is persistent and the web service's
   `DATABASE_URL` references the managed database.
6. Deploy. The web release step runs `alembic upgrade head` before the new web
   process is promoted. The worker starts the provider sync loop independently.
7. Verify the deployment using the checks below before attaching a public
   domain or announcing availability.

## Release verification

Replace `SERVICE.onrender.com` with the web service hostname:

```bash
curl -fsS https://SERVICE.onrender.com/api/health/live
curl -fsS https://SERVICE.onrender.com/api/health/ready
curl -fsS https://SERVICE.onrender.com/api/v1/sports
curl -fsS https://SERVICE.onrender.com/api/v1/competitions
curl -fsS https://SERVICE.onrender.com/openapi.json >/dev/null
```

Then verify in the Render dashboard:

- Latest web deploy is healthy and its pre-deploy migration step succeeded.
- Worker remains running and sync-run history advances without repeated failures.
- PostgreSQL storage, connection usage, and backup status are healthy.
- Provider requests remain within the provider's documented quota.
- Dashboard data labels clearly reflect the actual source freshness and coverage.

The readiness endpoint confirms application/database readiness; it does not
prove that provider data is current, complete, licensed for republication, or
factually correct.

## Public-access and security posture

- There is no visitor sign-up, login, or account requirement in this release.
- Do not set `JWT_SECRET_KEY` unless a later release deliberately activates
  identity and adds a reviewed access-control policy.
- Keep `CORS_ORIGINS` empty for the same-origin dashboard. If a separate trusted
  frontend is introduced, set only its exact HTTPS origin.
- Keep provider credentials server-side. Do not expose them through API
  responses, HTML, JavaScript, logs, or screenshots.
- The public API is read-only. Aggregate data freshness and data-quality
  summaries are public; sync history, issue details, reconciliation previews,
  and explicit match-report refresh require a validated sync-operator token.
- This first deployment intentionally does not configure visitor JWT
  authentication. Protected operator routes therefore fail closed until a
  separate operator-authentication policy is deliberately configured.
- Never add public ingestion, sync-trigger, data-editing, or administrative
  routes without authentication, authorization, rate limiting, and audit logging.
- Configure a custom domain and verify HTTPS before promotion.
- Add edge-level request rate limiting and abuse protection before broad public
  traffic. Monitor 4xx/5xx rates, latency, database connections, provider quota,
  worker restarts, and sync freshness.
- Confirm provider attribution, caching, display, and redistribution rights
  for each competition and data type before enabling public provider data.

## Provider licensing and data entitlement

The initial adapter uses football-data.org. Technical API access does not by
itself establish a right to redistribute the returned data commercially.

Before enabling the production sync worker:

- Obtain written confirmation from football-data.org that the selected
  subscription permits ChezaPort's intended public display, caching, historical
  retention, and any commercial use. The published terms do not clearly grant a
  blanket commercial redistribution licence.
- Confirm the selected subscription includes every resource ChezaPort consumes.
  The published pricing page distinguishes the basic Free tier (fixtures,
  schedules and league tables, with delayed scores) from the Free + Deep Data
  tier, which includes line-ups, substitutions, scorers, bookings/cards and
  squads. Player analytics and match reports depend on those deeper resources.
- Confirm the subscription is registered for the ChezaPort application/domain.
  The provider's terms describe API credentials as application-specific.
- Keep the API token confidential and server-side. Never put it in source
  control, browser code, logs, screenshots, or public API responses.
- Preserve the visible attribution already rendered by the dashboard:
  "Football data provided by the Football-Data.org API".
- Do not use provider-owned club logos or player photographs without separate
  permission from their respective rights holders.
- If the subscription is cancelled or data-display rights become uncertain,
  stop synchronization and follow the provider's data-retention and takedown
  requirements before continuing to serve cached provider data.

References:

- [Football-Data.org terms and conditions](https://www.football-data.org/about)
- [Football-Data.org FAQ and attribution guidance](https://www.football-data.org/documentation/faq)
- [Football-Data.org pricing and data-point coverage](https://www.football-data.org/pricing)

## Operations and recovery

Render continuously backs up paid PostgreSQL instances for point-in-time
recovery (PITR). The available recovery window depends on the Render workspace
plan (currently three days on Hobby and seven days on Pro or higher); confirm
the actual window in the database's Recovery page. PITR creates a separate
recovery database rather than overwriting the original, so validate the
recovered data before switching application connections.

Render also supports on-demand logical exports. These are retained in Render
for seven days after creation; download required exports and store them in
encrypted, durable storage outside Render for longer-term retention.

- Create an on-demand logical export before every schema-changing release.
- Test restoring an export into a separate database; a backup that has never
  been restored is not a verified recovery plan.
- Do not delete the original database until the replacement is validated and
  every service has been switched. Deleting a Render Postgres instance also
  deletes its recovery history and stored exports.
- Keep migrations backward-compatible with the currently running application
  when deploying multiple instances.
- If a release fails its pre-deploy step or health check, do not route traffic to
  it. Diagnose the failed migration or startup check before retrying.
- For an application rollback, redeploy the last known-good image/commit.
  Do not blindly downgrade a production database; use a forward corrective
  migration unless the specific downgrade has been rehearsed and is safe.
- Pause the sync worker during provider incidents or when data-display rights
  are uncertain. The public API should continue serving the last successfully
  stored data while freshness is disclosed honestly.

## Cost and capacity

The blueprint provisions paid services. Monitor actual Render pricing,
PostgreSQL storage, backup retention, worker uptime, and outbound provider
usage. Increase database and service capacity based on observed query latency,
connection utilization, and traffic—not speculative peak estimates.
