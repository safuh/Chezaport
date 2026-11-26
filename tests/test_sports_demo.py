"""Tests for the isolated synthetic demonstration dataset."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from chezaport.core.database import Base
from chezaport.sports.demo import seed_demo_dataset
from chezaport.sports.models import Competition, Fixture, Season, Team


@pytest.mark.asyncio
async def test_demo_dataset_is_synthetic_complete_and_idempotent() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        assert await seed_demo_dataset(factory) is True
        assert await seed_demo_dataset(factory) is False
        async with factory() as session:
            competition = await session.scalar(
                select(Competition).where(Competition.slug == "chezaport-synthetic-demo-league")
            )
            assert competition is not None
            assert "Fictional Data" in competition.name
            assert await session.scalar(select(func.count()).select_from(Team)) == 4
            assert await session.scalar(select(func.count()).select_from(Season)) == 1
            assert await session.scalar(select(func.count()).select_from(Fixture)) == 6
            fixtures = await session.scalars(select(Fixture))
            assert all(fixture.status == "finished" for fixture in fixtures.all())
    finally:
        await engine.dispose()
