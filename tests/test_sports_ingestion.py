"""Tests for provider-neutral sports ingestion upserts."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from chezaport.core.database import Base
from chezaport.sports.integrations.schemas import ProviderCompetition, ProviderTeam
from chezaport.sports.models import Competition, ExternalIDMapping, Sport, Team
from chezaport.sports.services.ingestion import IngestionOutcome, SportsIngestionService


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


async def seed_football(session) -> None:
    session.add(Sport(code="football", name="Association football"))
    await session.flush()


async def test_competition_import_is_idempotent(session_factory) -> None:
    async with session_factory() as session:
        await seed_football(session)
        service = SportsIngestionService(session, " Sample ")
        record = ProviderCompetition(
            external_id="league-1",
            name="Example League",
            slug="example-league",
        )

        first = await service.import_competitions([record])
        second = await service.import_competitions([record])

        assert first.records_seen == 1
        assert first.created == 1
        assert second.unchanged == 1
        assert second.items[0].canonical_id == first.items[0].canonical_id
        assert await session.scalar(select(func.count()).select_from(Competition)) == 1
        assert await session.scalar(select(func.count()).select_from(ExternalIDMapping)) == 1
        await session.commit()


async def test_team_import_updates_existing_canonical_record(session_factory) -> None:
    async with session_factory() as session:
        await seed_football(session)
        service = SportsIngestionService(session, "sample")
        original = ProviderTeam(
            external_id="team-1",
            name="Old Name",
            slug="sample-fc",
            short_name="OLD",
        )
        revised = original.model_copy(
            update={"name": "New Name", "short_name": "NEW"}
        )

        created = await service.import_teams([original])
        updated = await service.import_teams([revised])

        assert created.created == 1
        assert updated.updated == 1
        team = await session.get(Team, created.items[0].canonical_id)
        assert team is not None
        assert team.name == "New Name"
        assert team.short_name == "NEW"
        assert await session.scalar(select(func.count()).select_from(Team)) == 1
        await session.commit()


async def test_failed_record_does_not_block_valid_record(session_factory) -> None:
    async with session_factory() as session:
        await seed_football(session)
        service = SportsIngestionService(session, "sample")
        records = [
            ProviderTeam(
                external_id="unknown-sport-team",
                name="Unknown Sport Team",
                slug="unknown-sport-team",
                sport_code="rugby",
            ),
            ProviderTeam(
                external_id="valid-team",
                name="Valid Team",
                slug="valid-team",
            ),
        ]

        report = await service.import_teams(records)

        assert report.records_seen == 2
        assert report.failed == 1
        assert report.created == 1
        assert report.items[0].outcome == IngestionOutcome.FAILED
        assert "canonical sport is not seeded" in (report.items[0].error or "")
        assert await session.scalar(select(func.count()).select_from(Team)) == 1
        await session.commit()


async def test_competition_import_requires_seeded_country(session_factory) -> None:
    async with session_factory() as session:
        await seed_football(session)
        service = SportsIngestionService(session, "sample")
        record = ProviderCompetition(
            external_id="league-kenya",
            name="Kenyan League",
            slug="kenyan-league",
            country_code="KEN",
        )

        report = await service.import_competitions([record])

        assert report.failed == 1
        assert "canonical country is not seeded" in (report.items[0].error or "")
        assert await session.scalar(select(func.count()).select_from(Competition)) == 0
        await session.commit()
