"""Tests for explicit sports-provider runtime composition."""

import httpx
import pytest

from chezaport.core.config import Settings
from chezaport.sports.integrations.capabilities import ProviderResource
from chezaport.sports.integrations.errors import ProviderConfigurationError
from chezaport.sports.integrations.factory import build_sports_provider_registry


def test_registry_is_empty_without_external_credentials():
    registry = build_sports_provider_registry(Settings(_env_file=None))

    with pytest.raises(ProviderConfigurationError):
        registry.get("football-data-org")


def test_registry_routes_only_configured_competitions():
    settings = Settings(
        football_data_api_token="test-token",
        football_data_competition_codes=["PL", "CL"],
    )
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})),
        base_url="https://api.football-data.org/v4/",
    )
    try:
        registry = build_sports_provider_registry(settings, client=client)
        candidates = registry.providers_for_competition(
            "pl",
            resource=ProviderResource.FIXTURES,
        )

        assert len(candidates) == 1
        assert candidates[0].provider_name == "football-data-org"
        assert registry.providers_for_competition(
            "CL",
            resource=ProviderResource.TEAMS,
        )
    finally:
        import asyncio

        asyncio.run(client.aclose())


def test_registry_does_not_route_unconfigured_competitions():
    settings = Settings(
        football_data_api_token="test-token",
        football_data_competition_codes=["PL"],
    )
    registry = build_sports_provider_registry(settings)

    with pytest.raises(ProviderConfigurationError):
        registry.providers_for_competition("PD")
