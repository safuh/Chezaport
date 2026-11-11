"""Tests for explicit provider registration and competition routing."""

import pytest

from chezaport.sports.integrations.capabilities import (
    ProviderCapabilities,
    ProviderResource,
)
from chezaport.sports.integrations.errors import ProviderConfigurationError
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

ALL_RESOURCES = frozenset(ProviderResource)


class StubProvider:
    def __init__(
        self,
        name: str,
        *,
        competition_codes: frozenset[str] = frozenset({"PL"}),
        resources: frozenset[ProviderResource] = ALL_RESOURCES,
    ) -> None:
        self._name = name
        self._capabilities = ProviderCapabilities(
            competition_codes=competition_codes,
            resources=resources,
        )

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def fetch_competitions(
        self, sport_code: str
    ) -> list[ProviderCompetition]:
        return []

    async def fetch_seasons(
        self, competition_external_id: str
    ) -> list[ProviderSeason]:
        return []

    async def fetch_teams(
        self, competition_external_id: str
    ) -> list[ProviderTeam]:
        return []

    async def fetch_fixtures(
        self,
        competition_external_id: str,
        season_external_id: str,
        *,
        since: object | None = None,
    ) -> list[ProviderFixture]:
        return []


def test_registry_returns_candidates_in_configured_order() -> None:
    registry = SportsProviderRegistry()
    primary = StubProvider("football-data")
    secondary = StubProvider("alternate")
    registry.register(primary)
    registry.register(secondary)
    registry.set_route(
        CompetitionProviderRoute(" pl ", ("FOOTBALL-DATA", "Alternate"))
    )

    candidates = registry.providers_for_competition("PL")

    assert candidates == (primary, secondary)


def test_registry_filters_candidates_by_declared_resource_support() -> None:
    registry = SportsProviderRegistry()
    primary = StubProvider(
        "primary",
        resources=frozenset({ProviderResource.COMPETITIONS, ProviderResource.FIXTURES}),
    )
    secondary = StubProvider(
        "secondary",
        resources=frozenset({ProviderResource.FIXTURES, ProviderResource.TEAMS}),
    )
    registry.register(primary)
    registry.register(secondary)
    registry.set_route(CompetitionProviderRoute("PL", ("primary", "secondary")))

    assert registry.providers_for_competition(
        "PL", resource=ProviderResource.TEAMS
    ) == (secondary,)
    assert registry.providers_for_competition(
        "PL", resource=ProviderResource.FIXTURES
    ) == (primary, secondary)


def test_registry_rejects_resource_without_a_declared_provider() -> None:
    registry = SportsProviderRegistry()
    registry.register(
        StubProvider(
            "fixtures-only",
            resources=frozenset({ProviderResource.FIXTURES}),
        )
    )
    registry.set_route(CompetitionProviderRoute("PL", ("fixtures-only",)))

    with pytest.raises(
        ProviderConfigurationError,
        match="no routed provider declares support",
    ):
        registry.providers_for_competition(
            "PL", resource=ProviderResource.TEAMS
        )


def test_provider_capabilities_normalize_codes_and_resource_values() -> None:
    capabilities = ProviderCapabilities(
        competition_codes=frozenset({" pl ", " championship "}),
        resources=frozenset({ProviderResource.FIXTURES}),
    )

    assert capabilities.competition_codes == frozenset({"PL", "CHAMPIONSHIP"})
    assert capabilities.supports("pl", ProviderResource.FIXTURES)
    assert not capabilities.supports("BL1", ProviderResource.FIXTURES)


def test_provider_capabilities_require_explicit_coverage() -> None:
    with pytest.raises(ValueError, match="competition code"):
        ProviderCapabilities(
            competition_codes=frozenset(),
            resources=frozenset({ProviderResource.FIXTURES}),
        )


def test_registry_rejects_duplicate_provider_registration() -> None:
    registry = SportsProviderRegistry()
    registry.register(StubProvider("football-data"))

    with pytest.raises(ProviderConfigurationError, match="already registered"):
        registry.register(StubProvider("FOOTBALL-DATA"))


def test_registry_rejects_route_with_unregistered_provider() -> None:
    registry = SportsProviderRegistry()

    with pytest.raises(ProviderConfigurationError, match="unregistered"):
        registry.set_route(CompetitionProviderRoute("PL", ("missing",)))


def test_registry_requires_explicit_competition_route() -> None:
    registry = SportsProviderRegistry()

    with pytest.raises(ProviderConfigurationError, match="no provider route"):
        registry.providers_for_competition("PL")


def test_route_rejects_duplicate_provider_names() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        CompetitionProviderRoute("PL", ("football-data", "FOOTBALL-DATA"))
