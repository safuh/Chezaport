# Sports module

## Canonical reference data

Apply database migrations before running the bootstrap:

```bash
uv run alembic upgrade head
uv run python -m chezaport.sports.seed
```

The bootstrap command inserts the built-in sports supported by the current
`SportCode` enum. It is safe to run repeatedly and does not overwrite existing
sport records. It does not populate countries: country records should be added
only through an explicit reference-data import or provider integration, rather
than guessed from competition payloads.

## Ingestion order

The provider-neutral ingestion service expects canonical sports to exist.
Import related records in dependency order:

1. Competitions
2. Teams
3. Seasons (after competitions)
4. Fixtures (after competitions, seasons, and both teams)

A fixture's season must belong to its competition, and both teams must belong
to the competition's sport. Ingestion reports record-level failures and leaves
transaction ownership with the caller.


## Match reports and player analytics

The football-data.org match-report integration stores the latest normalized
provider report in `fixture_report_snapshots` and materializes queryable
events and squad participation in `fixture_match_events` and
`fixture_player_participation`. A successful report refresh replaces the
provider/fixture event and participation set in the same database transaction.
Repeated imports are idempotent; a corrected complete report replaces stale
records. Older cached report snapshots are lazily materialized when player
analytics are requested.

Read endpoints:

- `GET /api/v1/fixtures/{fixture_id}/report` returns the cached report without
  triggering provider requests. `refresh=true` is a protected operator action
  and requires a valid sync-operator bearer token.
- `GET /api/v1/players/{player_id}/statistics` aggregates confirmed events
  and appearances, optionally scoped by `competition_id` and `season_id`.
- `GET /api/v1/players/{player_id}/matches` returns paginated match-by-match
  participation and event totals. Bench selection is visible but is not
  counted as an appearance unless the player entered the match or started.
- `GET /api/v1/competitions/{competition_id}/player-leaderboard` ranks
  provider-linked players by goals, assists, or appearances for a required
  `season_id`. The `metric` parameter defaults to `goals`.

Player minutes are intentionally nullable: lineup and substitution events do
not always provide reliable on/off-pitch timestamps. The public dashboard now exposes season player rankings and selectable match-by-match
history. Provider identity coverage limits which canonical player profiles can
appear in event leaderboards.

Operational visibility is deliberately split by audience. The aggregate
`GET /api/v1/ops/sync-freshness` and `GET /api/v1/ops/data-quality` summaries are
public so visitors can understand source freshness and high-level integrity.
Detailed sync history, affected-record issue lists, fixture reconciliation,
provider-identity reconciliation, and explicit match-report refreshes require
a validated sync-operator bearer token. The public dashboard does not request
or display those internal diagnostics.
