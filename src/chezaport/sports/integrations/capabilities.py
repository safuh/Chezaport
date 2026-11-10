"""Explicit provider coverage declarations, independent of vendor implementations."""

from dataclasses import dataclass
from enum import StrEnum


class ProviderResource(StrEnum):
    """Normalized resource families a provider adapter can supply."""

    COMPETITIONS = "competitions"
    SEASONS = "seasons"
    TEAMS = "teams"
    FIXTURES = "fixtures"


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Declared competition and resource coverage for one provider.

    Empty or implicit coverage is intentionally not treated as universal support.
    Adapters must declare the canonical competition codes and resource families
    they can serve; the registry uses this declaration to filter route candidates.
    """

    competition_codes: frozenset[str]
    resources: frozenset[ProviderResource]

    def __post_init__(self) -> None:
        codes = frozenset(code.strip().upper() for code in self.competition_codes)
        resources = frozenset(ProviderResource(resource) for resource in self.resources)
        if not codes or any(not code for code in codes):
            raise ValueError("at least one non-blank competition code is required")
        if not resources:
            raise ValueError("at least one supported resource is required")
        object.__setattr__(self, "competition_codes", codes)
        object.__setattr__(self, "resources", resources)

    def supports(
        self, competition_code: str, resource: ProviderResource
    ) -> bool:
        """Return whether this provider explicitly declares the requested coverage."""
        return (
            competition_code.strip().upper() in self.competition_codes
            and resource in self.resources
        )
