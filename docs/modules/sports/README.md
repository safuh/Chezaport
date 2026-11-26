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

- `GET /api/v1/fixtures/{fixture_id}/report` returns the cached report;
  `refresh=true` requests a provider refresh.
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
