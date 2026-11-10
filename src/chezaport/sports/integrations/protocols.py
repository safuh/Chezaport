"""Structural interfaces implemented by sports-data provider adapters."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from chezaport.sports.integrations.schemas import (
    ProviderCompetition,
    ProviderFixture,
    ProviderSeason,
    ProviderTeam,
)


class SportsDataProvider(Protocol):
    """Async provider contract; adapters translate vendor payloads into schemas.

    Implementations must not leak vendor-specific models or status strings into
    the domain. Rate limits and transient failures should use typed exceptions.
    """

    @property
    def provider_name(self) -> str:
        """Stable, lowercase provider identifier used for external-ID mapping."""
        ...

    async def fetch_competitions(self, sport_code: str) -> Sequence[ProviderCompetition]:
        """Return competitions available for a sport."""
        ...

    async def fetch_seasons(
        self, competition_external_id: str
    ) -> Sequence[ProviderSeason]:
        """Return seasons for a provider competition."""
        ...

    async def fetch_teams(self, competition_external_id: str) -> Sequence[ProviderTeam]:
        """Return teams participating in a provider competition."""
        ...

    async def fetch_fixtures(
        self,
        competition_external_id: str,
        season_external_id: str,
        *,
        since: datetime | None = None,
    ) -> Sequence[ProviderFixture]:
        """Return fixtures, optionally updated or scheduled since a timestamp."""
        ...
