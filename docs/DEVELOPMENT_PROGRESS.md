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
- Keep identity optional and dormant for v1; no visitor sign-in requirement.
- Preserve health, database, and app-factory behavior.
- Keep CI independent of provider credentials and live network calls.

## Current repository state

- Repository: [safuh/Chezaport](https://github.com/safuh/Chezaport)
- Working branch: `feature/sports-platform-foundation`
- Latest pushed commit before the current uncommitted identity-role increment: `9733f2e` (operator sync monitoring and demo dataset)
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
| M4 | Sports domain, ingestion, provider adapter, manual and scheduled fixture sync | Implemented; provider credentials and live-plan verification pending |
| M5 | Read API and deterministic analytics | Implemented and contract-tested |
| M6 | Release verification | Local tests and CI/security workflows passing; provider and staging gates remain |
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
provider route. The read-only adapter, registry composition, one-shot sync, and
continuous fixture-refresh worker are implemented. Local credentials and live
feed verification remain pending. The provider documents delayed scores on its
free plan and plan-dependent live-score availability. Attribution and
data-use/redistribution rights must be confirmed before public production use.
No token is stored in the repository or chat.

## Remaining release gates

1. Run the updated GitHub Actions and CodeQL workflows on the next API
   increment; resolve any matrix or security findings.
2. Confirm GitHub secret scanning and push protection are enabled for the repo.
3. Configure the provider token locally and verify the EPL feed within the
   documented quota after confirming public-use terms.
4. Configure the fixture-refresh worker only after freshness, quota, and provider
   terms are approved; keep the job idempotent and provider tokens out of CI.
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
- The audit model records internal operational metadata. Read-only run-history and freshness views are public in v1; no public write/sync trigger or credential exposure is provided.


## Operator monitoring and reproducible demo data

- Added `GET /api/v1/ops/sync-runs` with provider/resource/status filters and pagination, plus `GET /api/v1/ops/sync-freshness` with a caller-configurable stale threshold. These GET-only endpoints are public in v1 and return non-secret operational metadata so the dashboard needs no user sign-in.
- Added `uv run python -m chezaport.sports.demo`: an idempotent, credential-free synthetic league with four fictional teams and six completed fixtures. Its display name explicitly labels the data fictional; the command never overwrites or deletes records.
- Added tests for operator authorization, sync history/freshness responses, and demo dataset idempotency.


## Identity roles and operator authorization increment (local, not yet pushed)

- Added migration `0007_identity_roles` with a constrained `users.role` field (`viewer`, `operator`, `admin`); existing users and new registrations default to `viewer`.
- Authentication access JWTs now carry the persisted role claim. Refresh rotation reloads the current role from the identity repository before minting the replacement access token, avoiding stale privilege claims.
- Added `create_sync_operator_token_validator`, which validates JWT signature, expiry, token type and subject, then checks the current database role. It grants only `operator` and `admin`; malformed tokens, refresh tokens, unknown users, and viewers are denied. Added a trusted-shell `python -m chezaport.identity.manage_roles` command to promote/demote existing users without a public privilege-escalation endpoint.
- Added explicit app-factory injection for the validator and documented host composition. No bootstrap administrator, default password, or committed secret is introduced.
- Migration uses Alembic batch operations so SQLite and PostgreSQL can both apply the role constraint.
- Verification: Ruff lint/format, mypy, and pytest passed: 134 passed, 2 skipped, 2 upstream deprecation warnings. The initial migration test caught SQLite's lack of direct `ALTER CHECK CONSTRAINT`; the migration was corrected to use batch mode and the full suite passed afterwards.
- This increment is local and has not yet been committed or pushed.


## Team cross-season comparison

- Added `GET /api/v1/teams/{team_id}/season-comparison?competition_id=...`.
- Returns each season in chronological order where the team recorded at least one completed fixture, including final table position, points, and full overall/home/away performance statistics. Seasons with no team results are omitted rather than represented as zero-performance seasons.
- Validates both competition and team identifiers and returns stable 404 responses for unknown resources.
- Added HTTP contract coverage for the comparison endpoint.


## Administrator user-management API

- Added `GET /api/v1/admin/users` with bounded pagination and a response that excludes password hashes and other authentication material.
- Added `PATCH /api/v1/admin/users/{user_id}/role` for explicit `viewer`, `operator`, and `admin` role changes.
- Both routes fail closed unless the host injects an administrator token validator; missing bearer tokens are rejected and denied tokens receive 403.
- The final administrator cannot be demoted. PostgreSQL row locking serializes administrator-count checks to reduce concurrent last-admin demotion races.
- The app factory now accepts `admin_token_validator`; production composition must supply `create_admin_token_validator` with the shared database session factory and configured JWT secret.


## Administrator API integration verification

- Added a database-backed HTTP contract test covering administrator listing, credential-field exclusion, viewer denial, role promotion, immediate privilege revocation after demotion despite an unexpired access token, last-administrator protection, and invalid role rejection.
- The API and validator are still deliberately composed by the host; the first administrator is provisioned through the trusted-shell role-management command rather than a public bootstrap endpoint.
- Local integration test: 1 passed. Full quality gates are being rerun for this increment.


## First-party sports dashboard

- Added a responsive same-origin web dashboard served at `/`; no separate frontend build pipeline, Node runtime, or third-party CDN is required.
- Competition and season selectors drive the existing public API. The dashboard renders league standings, all/upcoming/completed fixtures, competition scoring summaries, team season records, and recent form.
- All dynamic labels and table values are inserted as text nodes rather than HTML, reducing DOM injection risk. The dashboard uses only public read endpoints; operator/admin credentials are not stored in browser code.
- Added root-route tests and extended the sports API contract test to verify the dashboard is served alongside populated API data. The Docker smoke test now also fetches the dashboard from the built container.
- Configured setuptools package data and verified the HTML asset is present in both source distribution and wheel.
- Local verification: Ruff, mypy (58 source files), 13 focused app/admin tests, package build, and Twine validation passed. Full suite and browser-level visual testing remain to be run.


## Environment-driven identity composition

- Added optional `JWT_SECRET_KEY` configuration (minimum 32 characters) and bounded access/refresh token lifetime settings. No key is generated or committed.
- When configured, the application factory composes the standard SQLAlchemy registration/login/refresh/logout application; lifespan binds database-backed operator and administrator validators to the shared session factory. Explicit host-injected factories/validators continue to take precedence.
- Documented the local owner bootstrap: register a normal viewer, promote it through the trusted-shell role command, then authenticate. No public role escalation or default admin is introduced.
- Added an integration test proving a newly registered viewer is denied admin access, then the same still-valid access token gains current persisted admin/operator permissions only after a trusted database role change.

## Latest verification update

- Full local suite after the dashboard, container smoke, and environment-driven authentication changes: 145 passed, 2 skipped, 2 upstream deprecation warnings.
- Ruff formatting/lint and mypy (58 source files) passed; source distribution and wheel built, and both passed Twine validation.
- `make docker-test` passed on the dashboard increment: the image built, PostgreSQL became healthy, all seven Alembic revisions applied, `/` returned the dashboard, health/readiness checks passed, and the smoke stack/volume were removed.
- GitHub CI and CodeQL both passed for dashboard commit `cef73c5`. The subsequent container-smoke and auth-composition commits still require their own GitHub workflow results after push.


## Public first-release workflow and continuous data refresh (local increment)

- Removed visitor authentication from the read-only synchronization history and freshness endpoints. The dashboard can display freshness without user accounts; no public write/sync trigger was added.
- Added fixture-only synchronization for previously imported competitions. It performs one provider request per competition and records each attempt through the existing durable sync-run audit path.
- Added `--fixtures-only`, `--watch`, and `--interval-seconds` modes to the sync CLI. Watch mode runs a full catalogue import once, then refreshes fixture records on a bounded interval (minimum 60 seconds; default 120 seconds).
- Dashboard refreshes its database-backed view every 30 seconds and displays the last fixture sync time. Provider attribution is displayed when Football-Data.org is the active feed; synthetic demo data is labelled as synthetic.
- Documented that v1 visitors do not sign in, provider credentials remain server-side, and the free provider tier has delayed scores. Live score availability is plan-dependent and must be confirmed with the provider before promising real-time results.
- Added tests for fixture-only refresh, the requirement for an initial catalogue sync, public read-only freshness endpoints, and dashboard refresh/attribution behavior.
- Verification: full local suite 147 passed, 2 skipped; Ruff format/lint and mypy passed; dashboard JavaScript syntax check passed. Container smoke and latest CI for this uncommitted increment remain to be run.


## Match-centre and provider refresh correction

- Added a public team profile endpoint with country and home-ground metadata, including venue city and capacity.
- Added a match-centre panel to the dashboard. Selecting any fixture fetches its detail endpoint and displays competition, season, kickoff, status, round, and venue context.
- Fixture cards are now keyboard-operable buttons with selected-state semantics. Team intelligence includes canonical club profile metadata alongside season statistics.
- Fixed the live fixture polling request: football-data.org requires `dateFrom` and `dateTo` together. Incremental fixture refresh now sends both, covering the start date through one year ahead so recent corrections and upcoming fixtures are included.
- The user's local database was inspected: Premier League catalogue import succeeded (20 teams, 128 season records, 380 fixtures); the subsequent fixture-only refresh had failed with HTTP 400 because the adapter sent `dateFrom` without `dateTo`. This increment corrects that request and will be validated against the configured provider account.
- Made negative configuration tests independent of a developer's local `.env`, so live credentials do not make test outcomes machine-dependent.


## Full-season dashboard correctness

- Dashboard now paginates through every fixture in the selected season rather than silently using only the oldest 100. This matters for the live Premier League season, which currently contains 380 fixtures.
- Season headline totals now use the complete competition statistics endpoint instead of calculating from the first fixture page. Club count uses the full season participant catalogue.
- Fixture view now prioritizes the next 10 scheduled matches and latest 10 results; the Upcoming and Results tabs each show up to 20 records in chronological/reverse-chronological order respectively.
- League standings now include all clubs in the season schedule, including teams yet to play, with zeroed statistics until they record a completed result.


## Docker smoke harness correction

- Fixed a shell pipeline issue in `scripts/docker-smoke.sh`: `grep --quiet` could close the dashboard response pipe early, causing curl exit code 23 under `pipefail`. The smoke test now downloads the dashboard to a temporary file, checks the expected content, and removes the file during cleanup.

## Latest verification on the configured live-data environment

- The user's configured Football-Data.org account successfully completed a fixture-only refresh after the date-range correction: 280 fixtures fetched, 0 failed, 280 unchanged. The latest fixture freshness record is `succeeded`.
- The local Premier League 2026/27 catalogue contains 20 clubs and 380 fixtures. The dashboard now pages through all 380 rather than only the first 100.
- Latest full test suite: 147 passed, 2 skipped. Ruff formatting/lint and mypy passed.
- `make docker-test` passed after correcting the smoke script's curl/grep pipe handling. PostgreSQL migrations 0001–0007 applied; health, readiness, and dashboard checks succeeded; temporary containers, network, and volume were removed.


## Production-hardening and player-intelligence continuation — 2026-11-26

### Implemented in the current feature branch

- Added `GET /api/v1/players/{player_id}/career`. Career output is grouped by historical club and competition/season, includes membership periods, appearances, starts, goals, assists, cards, substitutions, and explicit provider-linkage/attribution coverage. Team attribution uses provider team identity and membership dates; unconfirmed or contradictory attribution is surfaced rather than silently assigned to a player's current club.
- Added `GET /api/v1/teams/{team_id}/player-contributions`, with competition/season filters, metric selection, deterministic ranking, and pagination. Historical membership players remain represented even when provider identity linkage is missing.
- Integrated player career and team contribution views into the existing vanilla JavaScript dashboard. Career panels now show club periods, competition/season breakdowns, goals, assists, cards, and clickable player links from team contribution rankings.
- Added a CI JavaScript syntax check for the single-file dashboard; this verifies parsing, not browser runtime behavior.
- Added migration `0010_player_analytics_indexes` for provider/team participation lookups and secondary-player event lookups. The migration test now verifies both indexes.
- Centralized lazy canonical report materialization in a shared backfill service. Player statistics, match history, leaderboards, career analytics, and team contributions now use it; snapshot rows are locked during backfill and canonical events/participations are committed before request-session teardown.
- Added a regression fixture with snapshot-only match data. The career endpoint materializes it, a subsequent team-contribution request remains idempotent, and a new session verifies the canonical rows persisted.
- Protected explicit match-report cache bypass, detailed sync history, data-quality issue lists, fixture reconciliation, and provider-identity reconciliation with the sync-operator validator. Public freshness and aggregate data-quality summaries remain available without visitor accounts.
- Removed detailed operational diagnostics from the public dashboard. It now requests only aggregate freshness and data-quality summaries, and no longer polls the data-quality summary every 30 seconds.
- Added baseline response security headers, same-origin isolation headers, dashboard CSP, and HTTPS HSTS.
- Added bounded per-process API rate limiting: 120 requests/minute for general public API traffic and 10 requests/minute for match reports, with rate-limit headers and HTTP 429 responses. Health checks are exempt.
- Configured the Render web command to trust forwarded client/protocol headers from Render ingress, enabling correct HTTPS detection and client-IP handling.
- Corrected the Render PostgreSQL plan from the invalid `1g` identifier to `0.5c-1g`, set 15 GB storage, and restricted database inbound access to the private network.
- Expanded deployment documentation for PostgreSQL PITR/logical exports, provider data entitlement, attribution, and operator/public access boundaries.

### Validation evidence

- Latest GitHub CI run #312 on head `dfc52d9` passed on Python 3.11, 3.12, and 3.13: **165 tests passed, 2 warnings**. Ruff formatting/lint, MyPy, dependency audit, package build, dashboard JavaScript syntax validation, and PostgreSQL + Docker Compose smoke test passed.
- Latest Security workflow #269 passed CodeQL Python analysis.
- The Render Blueprint was re-planned successfully as `exs-dc46r06i0phs739ar9fg` / plan `exe-dc4723qjnfac73bnojkg`, including trusted proxy headers and rate-limit environment variables. Automatic Blueprint sync remains disabled. No Render web service, worker, or database has been provisioned.
- The dashboard has only had JavaScript syntax validation; desktop/mobile browser runtime, console, network, and accessibility testing remain outstanding.

### Release blockers still open

- Configure the real `FOOTBALL_DATA_API_TOKEN` as a Render secret and confirm the subscription includes the Deep Data resources required for match reports, lineups, substitutions, scorers, bookings, and squads.
- Obtain written provider confirmation for public display, caching, historical retention, and any commercial redistribution. Attribution alone does not establish redistribution rights.
- Configure an edge rate limit before horizontal scaling or substantial public traffic. The current in-process limiter is intentionally single-instance and is not a distributed quota.
- Complete real desktop and mobile browser testing, including console/network inspection and accessibility checks.
- Provision Render resources only after the current CI run passes and the provider/licensing gate is resolved.
- Run a real production PostgreSQL backup export and restore drill after provisioning. Documentation is in place, but no production database exists to test.
- Complete a live provider sync, verify freshness, and run the production smoke test after deployment.
- Keep PR #2 open and in draft; do not merge until the accumulated branch diff, latest CI, security checks, and deployment acceptance criteria have been reviewed.



### Current Git state

- Branch: `feature/sports-platform-foundation`
- Head: `dfc52d97b16b56cc87e0611242e7cb3e02953438`
- PR #2: open and still draft; 238 commits ahead of `main`, 0 behind; 118 changed files in the accumulated PR diff.
- Do not merge yet. The latest CI and CodeQL checks pass, but the full accumulated 118-file diff still requires a final review before promotion.
