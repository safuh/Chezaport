"""Tests for provider-neutral sports ingestion upserts."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from chezaport.core.database import Base
from chezaport.sports.integrations.schemas import (
    ProviderCompetition,
    ProviderFixture,
    ProviderSeason,
    ProviderTeam,
)
from chezaport.sports.models import (
    Competition,
    ExternalIDMapping,
    Fixture,
    Season,
    Sport,
    Team,
)
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



async def test_season_and_fixture_import_resolve_dependencies(session_factory) -> None:
    from datetime import UTC, datetime

    async with session_factory() as session:
        await seed_football(session)
        service = SportsIngestionService(session, "sample")
        competition_report = await service.import_competitions(
            [
                ProviderCompetition(
                    external_id="league-1",
                    name="Example League",
                    slug="example-league",
                )
            ]
        )
        team_report = await service.import_teams(
            [
                ProviderTeam(
                    external_id="home-1",
                    name="Home FC",
                    slug="home-fc",
                ),
                ProviderTeam(
                    external_id="away-1",
                    name="Away FC",
                    slug="away-fc",
                ),
            ]
        )
        season_record = ProviderSeason(
            external_id="season-2026",
            competition_external_id="league-1",
            name="2026",
            start_date="2026-01-01",
            end_date="2026-12-31",
        )
        season_report = await service.import_seasons([season_record])
        fixture_record = ProviderFixture(
            external_id="fixture-1",
            competition_external_id="league-1",
            season_external_id="season-2026",
            home_team_external_id="home-1",
            away_team_external_id="away-1",
            kickoff_at=datetime(2026, 11, 10, 15, 0, tzinfo=UTC),
        )
        fixture_report = await service.import_fixtures([fixture_record])
        repeated_report = await service.import_fixtures([fixture_record])

        assert competition_report.created == 1
        assert team_report.created == 2
        assert season_report.created == 1
        assert fixture_report.created == 1
        assert repeated_report.unchanged == 1
        assert await session.scalar(select(func.count()).select_from(Season)) == 1
        assert await session.scalar(select(func.count()).select_from(Fixture)) == 1
        await session.commit()


async def test_fixture_import_reports_unresolved_dependencies(session_factory) -> None:
    from datetime import UTC, datetime

    async with session_factory() as session:
        await seed_football(session)
        service = SportsIngestionService(session, "sample")
        record = ProviderFixture(
            external_id="fixture-missing",
            competition_external_id="missing-league",
            season_external_id="missing-season",
            home_team_external_id="missing-home",
            away_team_external_id="missing-away",
            kickoff_at=datetime(2026, 11, 10, 15, 0, tzinfo=UTC),
        )

        report = await service.import_fixtures([record])

        assert report.failed == 1
        assert "unresolved competition provider ID" in (report.items[0].error or "")
        assert await session.scalar(select(func.count()).select_from(Fixture)) == 0
        await session.commit()
