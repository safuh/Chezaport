"""SQLite smoke test for the full Alembic migration chain."""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine


async def test_alembic_migrations_create_sports_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "migration-smoke.db"
    database_url = f"sqlite+aiosqlite:///{database_path}"
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    project_root = Path(__file__).resolve().parents[1]

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        cwd=project_root,
        env=env,
    )

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            tables = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
            indexes = await connection.run_sync(
                lambda sync_connection: {
                    table: {index["name"] for index in inspect(sync_connection).get_indexes(table)}
                    for table in ("fixture_match_events", "fixture_player_participation")
                }
            )
        assert {
            "sports",
            "countries",
            "venues",
            "competitions",
            "seasons",
            "teams",
            "players",
            "team_memberships",
            "fixtures",
            "external_id_mappings",
            "sports_sync_runs",
            "fixture_report_snapshots",
            "fixture_match_events",
            "fixture_player_participation",
            "users",
            "refresh_tokens",
            "alembic_version",
        } <= tables
        assert "ix_fixture_match_events_secondary_player" in indexes["fixture_match_events"]
        assert "ix_fixture_player_participation_team" in indexes["fixture_player_participation"]
    finally:
        await engine.dispose()

    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        check=True,
        cwd=project_root,
        env=env,
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        cwd=project_root,
        env=env,
    )
