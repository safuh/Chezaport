"""Tests for provider-neutral sports synchronization orchestration."""

from collections.abc import Sequence
from datetime import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from chezaport.core.database import Base
from chezaport.sports.integrations.capabilities import (
    ProviderCapabilities,
    ProviderResource,
)
from chezaport.sports.integrations.errors import (
    ProviderConfigurationError,
    ProviderUnavailableError,
)
from chezaport.sports.integrations.registry import (
    CompetitionProviderRoute,
    SportsProviderRegistry,
)
from chezaport.sports.integrations.schemas import (
    ProviderCompetition,
    ProviderFixture,
    ProviderSeason,
    ProviderTeam,
)
from chezaport.sports.models import Sport, Team
from chezaport.sports.services.sync import SportsSyncService


class StubProvider:
    def __init__(
        self,
        name: str,
        *,
        resources: frozenset[ProviderResource],
        teams: Sequence[ProviderTeam] = (),
        competitions: Sequence[ProviderCompetition] = (),
        failures_before_success: int = 0,
        failure: Exception | None = None,
    ) -> None:
        self._name = name
        self._capabilities = ProviderCapabilities(
            competition_codes=frozenset({"PL"}),
            resources=resources,
        )
        self.teams = tuple(teams)
        self.competitions = tuple(competitions)
        self.failures_before_success = failures_before_success
        self.failure = failure
        self.team_calls = 0
        self.competition_calls = 0
        self.season_calls = 0
        self.fixture_calls = 0

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def fetch_competitions(
        self, sport_code: str
    ) -> Sequence[ProviderCompetition]:
        self.competition_calls += 1
        return self.competitions

    async def fetch_seasons(self, competition_external_id: str) -> Sequence[ProviderSeason]:
        self.season_calls += 1
        return []

    async def fetch_teams(self, competition_external_id: str) -> Sequence[ProviderTeam]:
        self.team_calls += 1
        if self.failures_before_success > 0:
            self.failures_before_success -= 1
            raise self.failure or ProviderUnavailableError("temporary outage")
        if self.failure is not None:
            raise self.failure
        return self.teams

    async def fetch_fixtures(
        self,
        competition_external_id: str,
        season_external_id: str,
        *,
        since: datetime | None = None,
    ) -> Sequence[ProviderFixture]:
        self.fixture_calls += 1
        return []


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


def make_registry(*providers: StubProvider) -> SportsProviderRegistry:
    registry = SportsProviderRegistry()
    for provider in providers:
        registry.register(provider)
    registry.set_route(
        CompetitionProviderRoute("PL", tuple(provider.provider_name for provider in providers))
    )
    return registry


async def test_sync_teams_selects_first_provider_with_resource_support(
    session_factory,
) -> None:
    unsupported = StubProvider(
        "fixtures-only",
        resources=frozenset({ProviderResource.FIXTURES}),
    )
    selected = StubProvider(
        "teams-provider",
        resources=frozenset({ProviderResource.TEAMS}),
        teams=(
            ProviderTeam(
                external_id="team-1",
                name="Example FC",
                slug="example-fc",
            ),
        ),
    )
    registry = make_registry(unsupported, selected)
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    async with session_factory() as session:
        await seed_football(session)
        service = SportsSyncService(session, registry, retry_sleep=fake_sleep)

        report = await service.sync_teams("PL", "league-1")

        assert report.provider == "teams-provider"
        assert report.resource == ProviderResource.TEAMS
        assert report.competition_code == "PL"
        assert report.records_fetched == 1
        assert report.created == 1
        assert report.failed == 0
        assert report.completed_at >= report.started_at
        assert unsupported.team_calls == 0
        assert selected.team_calls == 1
        assert delays == []
        assert session.in_transaction()
        assert await session.scalar(select(func.count()).select_from(Team)) == 1
        await session.commit()


async def test_sync_retries_transient_provider_failure(
    session_factory,
) -> None:
    provider = StubProvider(
        "retry-provider",
        resources=frozenset({ProviderResource.TEAMS}),
        failures_before_success=1,
        teams=(
            ProviderTeam(
                external_id="team-1",
                name="Example FC",
                slug="example-fc",
            ),
        ),
    )
    registry = make_registry(provider)
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    async with session_factory() as session:
        await seed_football(session)
        service = SportsSyncService(session, registry, retry_sleep=fake_sleep)

        report = await service.sync_teams("PL", "league-1")

        assert report.created == 1
        assert provider.team_calls == 2
        assert delays == [0.5]
        await session.commit()


async def test_sync_does_not_fail_over_after_selected_provider_fails(
    session_factory,
) -> None:
    primary = StubProvider(
        "primary",
        resources=frozenset({ProviderResource.TEAMS}),
        failure=ProviderConfigurationError("invalid provider configuration"),
    )
    secondary = StubProvider(
        "secondary",
        resources=frozenset({ProviderResource.TEAMS}),
        teams=(
            ProviderTeam(
                external_id="team-1",
                name="Example FC",
                slug="example-fc",
            ),
        ),
    )
    registry = make_registry(primary, secondary)

    async with session_factory() as session:
        await seed_football(session)
        service = SportsSyncService(session, registry)

        with pytest.raises(ProviderConfigurationError, match="invalid provider configuration"):
            await service.sync_teams("PL", "league-1")

        assert primary.team_calls == 1
        assert secondary.team_calls == 0
        await session.rollback()


async def test_competition_discovery_requires_explicit_provider(
    session_factory,
) -> None:
    provider = StubProvider(
        "discovery-provider",
        resources=frozenset({ProviderResource.COMPETITIONS}),
        competitions=(
            ProviderCompetition(
                external_id="league-1",
                name="Premier League",
                slug="premier-league",
            ),
        ),
    )
    registry = SportsProviderRegistry()
    registry.register(provider)

    async with session_factory() as session:
        await seed_football(session)
        service = SportsSyncService(session, registry)

        report = await service.sync_competitions("discovery-provider", " FOOTBALL ")

        assert report.competition_code is None
        assert report.resource == ProviderResource.COMPETITIONS
        assert report.records_fetched == 1
        assert report.created == 1
        assert provider.competition_calls == 1
        await session.commit()


async def test_sync_rejects_unconfigured_resource_before_fetch(
    session_factory,
) -> None:
    provider = StubProvider(
        "fixtures-only",
        resources=frozenset({ProviderResource.FIXTURES}),
    )
    registry = make_registry(provider)

    async with session_factory() as session:
        service = SportsSyncService(session, registry)

        with pytest.raises(ProviderConfigurationError, match="no routed provider declares support"):
            await service.sync_teams("PL", "league-1")

        assert provider.team_calls == 0
