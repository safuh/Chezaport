"""Tests for the provider-neutral sports persistence schema."""

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from chezaport.core.database import Base
from chezaport.sports import models as sports_models  # noqa: F401


def test_sports_tables_are_registered_in_metadata() -> None:
    expected = {
        "sports",
        "countries",
        "venues",
        "competitions",
        "seasons",
        "teams",
        "players",
        "team_memberships",
        "fixtures",
    }

    assert expected <= set(Base.metadata.tables)


async def test_sports_schema_can_be_created_with_sqlite() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            table_names = await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
        assert "fixtures" in table_names
        assert "team_memberships" in table_names
    finally:
        await engine.dispose()
