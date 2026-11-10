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
