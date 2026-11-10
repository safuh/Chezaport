"""Explicit provider registration and competition-aware routing."""

from dataclasses import dataclass

from chezaport.sports.integrations.capabilities import ProviderResource
from chezaport.sports.integrations.errors import ProviderConfigurationError
from chezaport.sports.integrations.protocols import SportsDataProvider


@dataclass(frozen=True, slots=True)
class CompetitionProviderRoute:
    """Ordered provider candidates for one canonical competition code."""

    competition_code: str
    provider_names: tuple[str, ...]

    def __post_init__(self) -> None:
        code = self.competition_code.strip().upper()
        names = tuple(name.strip().lower() for name in self.provider_names)
        if not code:
            raise ValueError("competition_code must not be blank")
        if not names or any(not name for name in names):
            raise ValueError("at least one non-blank provider name is required")
        if len(set(names)) != len(names):
            raise ValueError("provider_names must not contain duplicates")
        object.__setattr__(self, "competition_code", code)
        object.__setattr__(self, "provider_names", names)


class SportsProviderRegistry:
    """In-memory registry; routing is explicit and never guesses provider coverage.

    The ordered route is a candidate list, not an automatic failover mechanism.
    When a resource is requested, candidates are filtered against each adapter's
    declared coverage. Callers must still classify failures before trying another
    candidate; this registry does not perform requests or failover.
    """

    def __init__(self) -> None:
        self._providers: dict[str, SportsDataProvider] = {}
        self._routes: dict[str, CompetitionProviderRoute] = {}

    def register(self, provider: SportsDataProvider) -> None:
        """Register one adapter under its stable provider identifier."""
        name = provider.provider_name.strip().lower()
        if not name:
            raise ProviderConfigurationError("provider_name must not be blank")
        if name in self._providers:
            raise ProviderConfigurationError(f"provider already registered: {name}")
        self._providers[name] = provider

    def set_route(self, route: CompetitionProviderRoute) -> None:
        """Set the ordered provider candidates for a competition."""
        missing = set(route.provider_names).difference(self._providers)
        if missing:
            names = ", ".join(sorted(missing))
            raise ProviderConfigurationError(
                f"route references unregistered provider(s): {names}"
            )
        self._routes[route.competition_code] = route

    def get(self, provider_name: str) -> SportsDataProvider:
        """Return a registered provider or raise a configuration error."""
        name = provider_name.strip().lower()
        try:
            return self._providers[name]
        except KeyError as exc:
            raise ProviderConfigurationError(
                f"provider is not registered: {name}"
            ) from exc

    def providers_for_competition(
        self,
        competition_code: str,
        *,
        resource: ProviderResource | None = None,
    ) -> tuple[SportsDataProvider, ...]:
        """Return route candidates, optionally limited to declared resource support.

        Omitting ~resource~ preserves route-inspection behavior. Before making
        a provider request, callers should specify the exact resource so a
        provider without declared coverage cannot be selected accidentally.
        """
        code = competition_code.strip().upper()
        try:
            route = self._routes[code]
        except KeyError as exc:
            raise ProviderConfigurationError(
                f"no provider route configured for competition: {code}"
            ) from exc

        candidates = tuple(self._providers[name] for name in route.provider_names)
        if resource is None:
            return candidates

        supported = tuple(
            provider
            for provider in candidates
            if provider.capabilities.supports(code, resource)
        )
        if not supported:
            raise ProviderConfigurationError(
                f"no routed provider declares support for {resource.value} "
                f"in competition {code}"
            )
        return supported
