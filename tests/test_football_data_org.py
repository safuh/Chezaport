"""Contract tests for the football-data.org adapter using mocked HTTP responses."""

from datetime import UTC, datetime

import httpx
import pytest
import pytest_asyncio

from chezaport.sports.domain.enums import FixtureStatus
from chezaport.sports.integrations.errors import (
    ProviderConfigurationError,
    ProviderRateLimitError,
)
from chezaport.sports.integrations.football_data_org import FootballDataOrgProvider


@pytest_asyncio.fixture
async def provider_factory():
    clients: list[httpx.AsyncClient] = []

    def build(handler):
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://api.football-data.org/v4/",
        )
        clients.append(client)
        return FootballDataOrgProvider("test-token", client=client)

    yield build
    for client in clients:
        await client.aclose()


@pytest.mark.asyncio
async def test_fetch_competitions_filters_configured_codes(provider_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Auth-Token"] == "test-token"
        return httpx.Response(
            200,
            json={
                "competitions": [
                    {
                        "id": 2021,
                        "name": "Premier League",
                        "code": "PL",
                        "type": "LEAGUE",
                        "area": {"code": "ENG", "name": "England"},
                    },
                    {"id": 2014, "name": "Primera Division", "code": "PD", "type": "LEAGUE"},
                ]
            },
        )

    provider = provider_factory(handler)
    competitions = await provider.fetch_competitions("football")

    assert len(competitions) == 1
    assert competitions[0].external_id == "2021"
    assert competitions[0].slug == "pl"
    assert competitions[0].country_code == "ENG"
    assert competitions[0].country_name == "England"


@pytest.mark.asyncio
async def test_fetch_seasons_uses_start_year_as_query_identifier(provider_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/competitions/2021")
        return httpx.Response(
            200,
            json={
                "id": 2021,
                "seasons": [
                    {
                        "id": 733,
                        "startDate": "2025-08-15",
                        "endDate": "2026-05-24",
                    }
                ],
                "currentSeason": {"id": 733},
            },
        )

    provider = provider_factory(handler)
    seasons = await provider.fetch_seasons("2021")

    assert len(seasons) == 1
    assert seasons[0].external_id == "2025"
    assert seasons[0].name == "2025/26"
    assert seasons[0].is_current is True


@pytest.mark.asyncio
async def test_fetch_teams_normalizes_team_records(provider_factory):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "teams": [
                    {
                        "id": 57,
                        "name": "Arsenal FC",
                        "shortName": "Arsenal",
                        "tla": "ARS",
                        "area": {"code": "ENG", "name": "England"},
                    }
                ]
            },
        )

    provider = provider_factory(handler)
    teams = await provider.fetch_teams("2021")

    assert len(teams) == 1
    assert teams[0].external_id == "57"
    assert teams[0].slug == "arsenal"
    assert teams[0].short_name == "ARS"
    assert teams[0].country_name == "England"


@pytest.mark.asyncio
async def test_fetch_fixtures_maps_status_scores_and_timezone(provider_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["season"] == "2025"
        return httpx.Response(
            200,
            json={
                "matches": [
                    {
                        "id": 999,
                        "utcDate": "2025-08-16T16:30:00Z",
                        "status": "FINISHED",
                        "matchday": 1,
                        "competition": {"id": 2021},
                        "season": {"startDate": "2025-08-15"},
                        "homeTeam": {"id": 57},
                        "awayTeam": {"id": 58},
                        "score": {"fullTime": {"home": 2, "away": 1}},
                    }
                ]
            },
        )

    provider = provider_factory(handler)
    fixtures = await provider.fetch_fixtures("2021", "2025", since=datetime(2025, 8, 1, tzinfo=UTC))

    assert len(fixtures) == 1
    assert fixtures[0].status is FixtureStatus.FINISHED
    assert fixtures[0].home_score == 2
    assert fixtures[0].away_score == 1
    assert fixtures[0].season_external_id == "2025"
    assert fixtures[0].kickoff_at.utcoffset().total_seconds() == 0


@pytest.mark.asyncio
async def test_rate_limit_is_translated_to_typed_error(provider_factory):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "30"})

    provider = provider_factory(handler)
    with pytest.raises(ProviderRateLimitError) as error:
        await provider.fetch_competitions("football")

    assert error.value.retry_after_seconds == 30


@pytest.mark.asyncio
async def test_forbidden_resource_is_reported_as_configuration_error(provider_factory):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    provider = provider_factory(handler)
    with pytest.raises(ProviderConfigurationError):
        await provider.fetch_competitions("football")


def test_provider_requires_a_nonblank_token():
    with pytest.raises(ProviderConfigurationError):
        FootballDataOrgProvider("   ")
