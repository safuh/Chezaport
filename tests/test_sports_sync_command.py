"""Tests for the manual, transaction-scoped sports information sync command."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from chezaport.core.config import Settings
from chezaport.core.database import Base
from chezaport.sports.domain.enums import FixtureStatus
from chezaport.sports.integrations.capabilities import ProviderCapabilities, ProviderResource
from chezaport.sports.integrations.errors import ProviderConfigurationError
from chezaport.sports.integrations.registry import SportsProviderRegistry
from chezaport.sports.integrations.schemas import (
    ProviderCompetition,
    ProviderFixture,
    ProviderSeason,
    ProviderTeam,
)
from chezaport.sports.models import Competition, Country, Fixture, Season, Sport, Team
from chezaport.sports.sync import synchronize_competitions, synchronize_fixtures


class StubFootballProvider:
    provider_name = "football-data-org"
    capabilities = ProviderCapabilities(
        competition_codes=frozenset({"PL"}),
        resources=frozenset(ProviderResource),
    )

    async def fetch_competitions(self, sport_code: str):
        assert sport_code == "football"
        return (
            ProviderCompetition(
                external_id="2021",
                name="Premier League",
                slug="pl",
                country_code="ENG",
                country_name="England",
            ),
        )

    async def fetch_seasons(self, competition_external_id: str):
        assert competition_external_id == "2021"
        return (
            ProviderSeason(
                external_id="2025",
                competition_external_id="2021",
                name="2025/26",
                start_date=date(2025, 8, 1),
                end_date=date(2026, 5, 30),
                is_current=True,
            ),
        )

    async def fetch_teams(self, competition_external_id: str):
        assert competition_external_id == "2021"
        return (
            ProviderTeam(external_id="57", name="Arsenal FC", slug="arsenal"),
            ProviderTeam(external_id="58", name="Aston Villa FC", slug="aston-villa"),
        )

    async def fetch_fixtures(
        self,
        competition_external_id: str,
        season_external_id: str,
        *,
        since: datetime | None = None,
    ):
        assert competition_external_id == "2021"
        assert season_external_id == "2025"
        return (
            ProviderFixture(
                external_id="fixture-1",
                competition_external_id="2021",
                season_external_id="2025",
                home_team_external_id="57",
                away_team_external_id="58",
                kickoff_at=datetime(2025, 8, 16, 16, 30, tzinfo=UTC),
                status=FixtureStatus.FINISHED,
                home_score=2,
                away_score=1,
                round_name="1",
            ),
        )


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
def registry():
    result = SportsProviderRegistry()
    provider = StubFootballProvider()
    result.register(provider)
    from chezaport.sports.integrations.registry import CompetitionProviderRoute

    result.set_route(CompetitionProviderRoute("PL", (provider.provider_name,)))
    return result


@pytest.mark.asyncio
async def test_manual_sync_imports_catalogue_teams_season_and_fixtures(session_factory, registry):
    settings = Settings(
        football_data_api_token="test-token",
        football_data_competition_codes=["PL"],
    )

    reports = await synchronize_competitions(settings, session_factory, registry, ["PL"])

    assert [report.resource for report in reports] == [
        ProviderResource.COMPETITIONS,
        ProviderResource.SEASONS,
        ProviderResource.TEAMS,
        ProviderResource.FIXTURES,
    ]
    assert sum(report.created for report in reports) == 5
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Sport)) == 1
        assert await session.scalar(select(func.count()).select_from(Competition)) == 1
        assert await session.scalar(select(func.count()).select_from(Country)) == 1
        assert await session.scalar(select(func.count()).select_from(Season)) == 1
        assert await session.scalar(select(func.count()).select_from(Team)) == 2
        assert await session.scalar(select(func.count()).select_from(Fixture)) == 1


@pytest.mark.asyncio
async def test_manual_sync_is_idempotent(session_factory, registry):
    settings = Settings(
        football_data_api_token="test-token",
        football_data_competition_codes=["PL"],
    )

    await synchronize_competitions(settings, session_factory, registry, ["PL"])
    reports = await synchronize_competitions(settings, session_factory, registry, ["PL"])

    assert sum(report.created for report in reports) == 0
    assert sum(report.unchanged for report in reports) == 5


@pytest.mark.asyncio
async def test_manual_sync_requires_provider_token(session_factory, registry):
    with pytest.raises(ProviderConfigurationError):
        await synchronize_competitions(Settings(), session_factory, registry, ["PL"])


@pytest.mark.asyncio
async def test_manual_sync_rejects_unconfigured_competition(session_factory, registry):
    settings = Settings(
        football_data_api_token="test-token",
        football_data_competition_codes=["PL"],
    )

    with pytest.raises(ProviderConfigurationError):
        await synchronize_competitions(settings, session_factory, registry, ["PD"])


@pytest.mark.asyncio
async def test_fixture_refresh_only_updates_existing_competition(session_factory, registry):
    settings = Settings(
        football_data_api_token="test-token",
        football_data_competition_codes=["PL"],
    )
    await synchronize_competitions(settings, session_factory, registry, ["PL"])

    reports = await synchronize_fixtures(
        settings,
        session_factory,
        registry,
        ["PL"],
        since=datetime(2025, 8, 1, tzinfo=UTC),
    )

    assert len(reports) == 1
    assert reports[0].resource is ProviderResource.FIXTURES
    assert reports[0].records_fetched == 1
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Fixture)) == 1


@pytest.mark.asyncio
async def test_fixture_refresh_requires_initial_full_sync(session_factory, registry):
    settings = Settings(
        football_data_api_token="test-token",
        football_data_competition_codes=["PL"],
    )
    with pytest.raises(RuntimeError, match="run a full sync first"):
        await synchronize_fixtures(settings, session_factory, registry, ["PL"])
