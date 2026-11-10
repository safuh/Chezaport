"""Tests for idempotent canonical sports bootstrap."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from chezaport.core.database import Base
from chezaport.sports.models import Sport
from chezaport.sports.services.bootstrap import seed_default_sports


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def test_seed_default_sports_creates_football(session_factory) -> None:
    async with session_factory() as session:
        created = await seed_default_sports(session)

        sport = await session.scalar(select(Sport).where(Sport.code == "football"))
        assert created == 1
        assert sport is not None
        assert sport.name == "Association football"
        await session.commit()


async def test_seed_default_sports_is_idempotent(session_factory) -> None:
    async with session_factory() as session:
        first_created = await seed_default_sports(session)
        second_created = await seed_default_sports(session)

        assert first_created == 1
        assert second_created == 0
        assert await session.scalar(select(func.count()).select_from(Sport)) == 1
        await session.commit()


async def test_seed_does_not_overwrite_existing_sport(session_factory) -> None:
    async with session_factory() as session:
        session.add(Sport(code="football", name="Football", is_active=False))
        await session.flush()

        created = await seed_default_sports(session)
        sport = await session.scalar(select(Sport).where(Sport.code == "football"))

        assert created == 0
        assert sport is not None
        assert sport.name == "Football"
        assert sport.is_active is False
        await session.commit()
