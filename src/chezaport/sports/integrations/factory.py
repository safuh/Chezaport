"""Application composition helpers for configured sports-data providers."""

import httpx

from chezaport.core.config import Settings
from chezaport.sports.integrations.capabilities import ProviderResource
from chezaport.sports.integrations.football_data_org import FootballDataOrgProvider
from chezaport.sports.integrations.registry import (
    CompetitionProviderRoute,
    SportsProviderRegistry,
)


def build_sports_provider_registry(
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
) -> SportsProviderRegistry:
    """Build the provider registry from explicit runtime configuration.

    An absent token deliberately produces an empty registry: local development
    and test environments remain fully usable without external credentials.
    """
    registry = SportsProviderRegistry()
    token = settings.football_data_api_token
    if not token or not token.strip():
        return registry

    codes = frozenset(settings.football_data_competition_codes)
    provider = FootballDataOrgProvider(token, competition_codes=codes, client=client)
    registry.register(provider)
    for code in sorted(codes):
        registry.set_route(CompetitionProviderRoute(code, (provider.provider_name,)))
    return registry


def provider_resources() -> frozenset[ProviderResource]:
    """Return the resource set supported by the current football data adapter."""
    return frozenset(ProviderResource)
