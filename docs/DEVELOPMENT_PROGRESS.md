# Chezaport development progress

## Product direction

Chezaport is a backend-first football information and analysis platform. The
initial release is a modular monolith with a provider-neutral data model and
football-first public API. It is not a frontend or mobile application.

## Engineering constraints

- No Redis, brokers, AI features, or premature microservices.
- Free-first development; no paid provider or paid hosting requirement for local
  development.
- External provider use requires verified competition coverage, quota, freshness,
  attribution, and data-use/redistribution rights.
- Preserve existing authentication, health, database, and app-factory behavior.
- Keep CI independent of provider credentials and live network calls.

## Current repository state

- Repository: [safuh/Chezaport](https://github.com/safuh/Chezaport)
- Working branch: `feature/sports-platform-foundation`
- Latest pushed commit: `b9afbbd` (competition-season statistics)
- Local working directory: `/home/harry/AceCode/FastApiBackbone-CLI/Chezaport`
- Runtime: Python 3.11 virtual environment, uv, SQLite local default, PostgreSQL
  support, Podman-compatible Docker CLI.

## Milestones

| ID | Milestone | State |
| --- | --- | --- |
| M0 | Repository baseline and constraints | Complete |
| M1 | Application and API foundation | Complete |
| M2 | Persistence, identity, migrations | Implemented; SQLite and PostgreSQL migrations verified |
| M3 | Optional identity/JWT lifecycle | Implemented and tested |
| M4 | Sports domain, ingestion, provider adapter, and manual sync orchestration | Implemented; live credentials and scheduled sync pending |
| M5 | Read API and deterministic analytics | Implemented and contract-tested |
| M6 | Release verification | Local tests, package build, and dependency audit passed; latest GitHub CI/CodeQL run pending |
| M7 | Staging/production operations | Compose assets and container smoke passed; hosted infrastructure pending |

## Work completed in this development increment

- Added read APIs for countries, venues, teams, competition seasons, player
  search and profiles, and date-aware team squads with historical registration
  details. Catalogue queries support bounded pagination and filters.
- Added API contract coverage for player registration history and as-of squad
  membership, including exclusion before a registration's start date.
- Added a fixture detail endpoint that joins canonical competition, season, team,
  and optional venue context; missing fixture IDs return a stable 404 response.
- Added competition-season statistics for completed-match count, total and average
  goals, home/away goals, home wins, draws, away wins, and highest-scoring match.
- Added deterministic football standings from completed fixtures using 3-1-0
  scoring and documented tie-break ordering.
- Added recent team form and head-to-head aggregation services.
- Added regression coverage proving scheduled fixtures do not affect competition statistics.
- Added versioned read endpoints for sports, competitions, fixtures, competition
  statistics, standings, team form, and head-to-head results.
- Added analytics and HTTP contract tests, including exclusion of unfinished
  fixtures.
- Added a dedicated `staging` settings profile. Staging and production now both
  require PostgreSQL, disable debug mode, and use JSON logs.
- Added separate staging and production Compose definitions and deployment
  scripts. Both bind to loopback and require an external TLS proxy/ingress.
- Improved the Docker image to install locked runtime dependencies without
  building/installing the project wheel in the image; `PYTHONPATH` points to
  the source tree and the final image remains non-root.
- Added a deployment runbook and corrected the MVP acceptance tracker so
  implementation, verification, and infrastructure provisioning are distinct.
- Integrated three upstream commits, including provider-neutral sync
  orchestration, before resuming local work.
- Implemented a read-only football-data.org v4 adapter for competitions,
  seasons, teams, and fixtures, including provider status normalization,
  timeout/server/rate-limit handling, and a configurable provider registry.
- Added mocked HTTP contract tests for response normalization, credentials,
  rate-limit behavior, and explicit competition routing.
- Added a manual one-shot sync CLI that imports the configured competition
  catalogue, seasons, teams, and fixtures in one transaction. It aborts on
  record-level ingestion failures and keeps credentials out of command output.
- Added country metadata upsert from provider area names/codes so competition
  ingestion does not depend on a separately pre-seeded country catalogue.
- Added a dependency audit gate using the locked runtime requirements and OSV,
  plus a CodeQL security-extended Python workflow and weekly Dependabot updates
  for Python packages and GitHub Actions.
- The audit identified vulnerable versions of certifi, Mako, and PyJWT; upgraded
  them to certifi 2026.11.20, Mako 1.4.3, and PyJWT 2.15.1.
- Passed the subsequent runtime dependency audit with no known vulnerabilities.
- Exposed optional provider credentials and competition codes in staging and
  production Compose environments without enabling a provider when no token is
  configured.
- Changed the local Docker smoke port to a configurable loopback binding
  (default `127.0.0.1:18080`) so it does not conflict with a developer API on
  port 8000.
- CI remains independent of provider credentials and live sports-data calls.

- Added cross-season competition comparison: each season reports completed-match
  scoring, home/draw/away outcomes, number of teams with results, final-table
  leader and highest-scoring match. Seasons without completed fixtures remain
  visible with null leader/average values rather than fabricated results.
- Added team-season performance endpoint with overall and home/away records,
  goals, clean sheets, win rate and biggest victory.

## Verification completed

- `make check` before the latest catalogue API increment: 127 passed,
  2 skipped, and 2 upstream dependency deprecation warnings. Formatting,
  Ruff lint, and mypy passed.
- `make check`: 127 passed, 2 skipped, and 2 upstream dependency deprecation
  warnings after the country/venue API increment. Formatting, Ruff lint, and
  mypy passed.
- `make check` after the fixture detail endpoint: 127 passed, 2 skipped, and
  2 upstream dependency deprecation warnings; formatting, Ruff lint, and mypy passed.
- `make check` after competition statistics: 128 passed, 2 skipped, and 2
  upstream dependency deprecation warnings; formatting, Ruff lint, and mypy passed.
- `make check` after team-season statistics and cross-season comparison: 130 passed,
  2 skipped, and 2 upstream dependency deprecation warnings; formatting, Ruff lint,
  and mypy passed.
- `make audit`: passed; OSV reported no known vulnerabilities in the locked
  runtime dependency set after upgrading certifi, Mako, and PyJWT.
- GitHub Actions CI and the CodeQL security-extended workflow both passed
  for commit `212ed72`; the country/venue API increment will trigger a fresh
  run when pushed.
- Staging and production Compose configurations parse successfully with a
  placeholder PostgreSQL URL.
- PostgreSQL-specific tests against a temporary local PostgreSQL 17 container:
  2 passed. The temporary container was removed after the run.
- `make docker-test`: passed. The image built, PostgreSQL became healthy, API
  liveness/readiness returned `ok/ready`, all five Alembic revisions applied,
  and the test stack/volume were removed. The smoke port is configurable and
  defaults to loopback port 18080 to avoid conflicts with local port 8000.
- `uv build`: source distribution and wheel built successfully with the
  provider adapter and manual sync command included.
- `twine check dist/*`: both distribution artifacts passed.
- Staging and production Compose configurations parsed successfully with
  PostgreSQL URLs; all deployment shell scripts passed `bash -n`.
- Docker smoke uses Podman on the local development host; it built the updated
  image, verified liveness/readiness, applied all five Alembic revisions, and
  removed the temporary containers, network, and volume.

## Provider decision gate

The EPL (`PL`) / football-data.org technical pilot is the selected initial
provider route. The read-only adapter, registry composition, and manual one-shot sync command
are implemented. Local credentials, live feed verification, and an optional
scheduled sync remain pending. The provider documents a 10 calls/minute free-plan
limit and plan-dependent coverage. Attribution and data-use/redistribution
rights must be confirmed before public production use. No token is stored in the
repository or chat.

## Remaining release gates

1. Run the updated GitHub Actions and CodeQL workflows on the next API
   increment; resolve any matrix or security findings.
2. Confirm GitHub secret scanning and push protection are enabled for the repo.
3. Configure the provider token locally and verify the EPL feed within the
   documented quota after confirming public-use terms.
4. Add a scheduler only after freshness, quota, and provider terms are approved;
   keep scheduled jobs idempotent and provider tokens out of CI.
5. Provision real staging infrastructure (host, dedicated PostgreSQL, domain,
   TLS/ingress, and protected secrets), deploy, and run smoke tests.
6. Provision production infrastructure, encrypted backups, restore drills,
   monitoring, edge rate limiting, and an operational rollback procedure.

A hosted staging/production deployment cannot be completed from this repository
alone: the owner must select/provision the infrastructure and provide protected
runtime configuration outside Git.

## Synchronization observability foundation

- Added `sports_sync_runs` with provider/resource/competition scope, lifecycle status, UTC timestamps, fetched/seen/created/updated/unchanged/failed counters, and a bounded error summary.
- Added indexes for recent-run and provider/resource freshness queries, plus database constraints for valid states, non-negative counters, and timestamp ordering.
- The CLI sync path now supplies an independent audit session factory. Each attempt is committed as `running` before the provider call and finalized in a separate transaction, so a later ingestion rollback does not erase the failure record. Error summaries deliberately store exception type and a generic message rather than upstream exception text, which can contain request details.
- The audit model is an internal operational record; no unauthenticated public endpoint exposes it. An authenticated operator view and freshness thresholds remain follow-up work.


## Operator monitoring and reproducible demo data

- Added `GET /api/v1/ops/sync-runs` with provider/resource/status filters and pagination, plus `GET /api/v1/ops/sync-freshness` with a caller-configurable stale threshold.
- Both endpoints fail closed and delegate bearer-token validation and operator-role authorization to the host identity composition layer through `app.state.sync_operator_token_validator`. This repository's generic auth foundation does not yet define application roles, so the endpoints return 503 until the consuming app wires a real validator. No token-presence-only shortcut is accepted.
- Added `uv run python -m chezaport.sports.demo`: an idempotent, credential-free synthetic league with four fictional teams and six completed fixtures. Its display name explicitly labels the data fictional; the command never overwrites or deletes records.
- Added tests for operator authorization, sync history/freshness responses, and demo dataset idempotency.
