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
- Updated upstream baseline: `0896e69`
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
| M4 | Sports domain, ingestion, and sync orchestration | Implemented; live provider adapter pending |
| M5 | Read API and deterministic analytics | Implemented and contract-tested |
| M6 | Release verification | Local gates passed; CI/security gates pending |
| M7 | Staging/production operations | Compose assets and smoke test passed; hosted infrastructure pending |

## Work completed in this development increment

- Added deterministic football standings from completed fixtures using 3-1-0
  scoring and documented tie-break ordering.
- Added recent team form and head-to-head aggregation services.
- Added versioned read endpoints for sports, competitions, fixtures,
  standings, team form, and head-to-head results.
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

## Verification completed

- `make check`: 112 passed, 2 skipped, 2 dependency deprecation warnings.
  Formatting, Ruff lint, and mypy all passed.
- PostgreSQL-specific tests against a temporary local PostgreSQL 17 container:
  2 passed. The temporary container was removed after the run.
- `make docker-test`: passed. The image built, PostgreSQL became healthy, API
  liveness/readiness returned `ok/ready`, all five Alembic revisions applied,
  and the test stack/volume were removed.
- `uv build`: source distribution and wheel built successfully.
- `twine check dist/*`: both distribution artifacts passed.
- Staging and production Compose configurations parsed successfully with
  PostgreSQL URLs; all deployment shell scripts passed `bash -n`.
- The package build emits setuptools deprecation warnings for the current
  license metadata/classifier. They do not fail the build, but should be cleaned
  up before a future packaging-toolchain upgrade.

## Provider decision gate

The EPL (`PL`) / football-data.org technical pilot is the selected initial
provider route. The authenticated adapter and scheduled synchronization remain
to be completed after the API token is configured locally. The free plan is
limited to 10 calls/minute and delayed scores/schedules; attribution and
data-use/redistribution rights must be confirmed before public production use.
No token is stored in the repository or chat.

## Remaining release gates

1. Run the updated GitHub Actions workflow on the pushed branch and resolve any
   matrix-specific failures.
2. Complete dependency audit and secret scanning.
3. Implement the football-data.org adapter and authenticated sync command with
   mocked HTTP tests; never require a provider token in CI.
4. Configure the provider token locally and verify the EPL feed within its free
   quota after confirming public-use terms.
5. Provision real staging infrastructure (host, dedicated PostgreSQL, domain,
   TLS/ingress, and protected secrets), deploy, and run smoke tests.
6. Provision production infrastructure, encrypted backups, restore drills,
   monitoring, edge rate limiting, and an operational rollback procedure.

A hosted staging/production deployment cannot be completed from this repository
alone: the owner must select/provision the infrastructure and provide protected
runtime configuration outside Git.
