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
            "users",
            "refresh_tokens",
            "alembic_version",
        } <= tables
    finally:
        await engine.dispose()
