"""Provider-neutral orchestration for sports-data synchronization."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from chezaport.sports.integrations.capabilities import ProviderResource
from chezaport.sports.integrations.errors import ProviderConfigurationError
from chezaport.sports.integrations.protocols import SportsDataProvider
from chezaport.sports.integrations.registry import SportsProviderRegistry
from chezaport.sports.integrations.retry import retry_provider_call
from chezaport.sports.services.ingestion import IngestionReport, SportsIngestionService

RecordT = TypeVar("RecordT")
FetchRecords = Callable[[], Awaitable[Sequence[RecordT]]]
ImportRecords = Callable[[tuple[RecordT, ...]], Awaitable[IngestionReport]]
Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class SportsSyncReport:
    """Result of one provider fetch and canonical ingestion operation."""

    provider: str
    resource: ProviderResource
    competition_code: str | None
    started_at: datetime
    completed_at: datetime
    records_fetched: int
    ingestion: IngestionReport

    @property
    def records_seen(self) -> int:
        """Number of fetched records presented to the ingestion service."""
        return self.ingestion.records_seen

    @property
    def created(self) -> int:
        return self.ingestion.created

    @property
    def updated(self) -> int:
        return self.ingestion.updated

    @property
    def unchanged(self) -> int:
        return self.ingestion.unchanged

    @property
    def failed(self) -> int:
        return self.ingestion.failed


class SportsSyncService:
    """Coordinate provider selection, bounded fetch retries, and ingestion.

    The caller owns the AsyncSession and its transaction. This service never
    commits, rolls back, or creates sessions. Competition discovery requires
    an explicitly selected provider because no canonical competition code is
    available until discovery has returned records.

    Competition-scoped operations select the first route candidate that
    declares support for the requested resource. A fetch failure is propagated;
    the service never silently fails over to another provider.
    """

    def __init__(
        self,
        session: AsyncSession,
        registry: SportsProviderRegistry,
        *,
        retry_max_attempts: int = 3,
        retry_sleep: Sleep = asyncio.sleep,
    ) -> None:
        if retry_max_attempts < 1:
            raise ValueError("retry_max_attempts must be at least 1")
        self._session = session
        self._registry = registry
        self._retry_max_attempts = retry_max_attempts
        self._retry_sleep = retry_sleep

    async def sync_competitions(
        self,
        provider_name: str,
        sport_code: str,
    ) -> SportsSyncReport:
        """Discover competitions through an explicitly selected provider."""
        normalized_sport = sport_code.strip().lower()
        if not normalized_sport:
            raise ValueError("sport_code must not be blank")
        provider = self._registry.get(provider_name)
        if ProviderResource.COMPETITIONS not in provider.capabilities.resources:
            raise ProviderConfigurationError(
                f"provider {provider.provider_name} does not declare "
                "support for competitions"
            )
        return await self._execute(
            provider=provider,
            competition_code=None,
            resource=ProviderResource.COMPETITIONS,
            fetch=lambda: provider.fetch_competitions(normalized_sport),
            importer=SportsIngestionService(
                self._session, provider.provider_name
            ).import_competitions,
        )

    async def sync_seasons(
        self,
        competition_code: str,
        competition_external_id: str,
    ) -> SportsSyncReport:
        """Fetch and ingest seasons for a mapped provider competition."""
        provider = self._routed_provider(competition_code, ProviderResource.SEASONS)
        return await self._execute(
            provider=provider,
            competition_code=competition_code,
            resource=ProviderResource.SEASONS,
            fetch=lambda: provider.fetch_seasons(competition_external_id),
            importer=SportsIngestionService(
                self._session, provider.provider_name
            ).import_seasons,
        )

    async def sync_teams(
        self,
        competition_code: str,
        competition_external_id: str,
    ) -> SportsSyncReport:
        """Fetch and ingest teams for a provider competition."""
        provider = self._routed_provider(competition_code, ProviderResource.TEAMS)
        return await self._execute(
            provider=provider,
            competition_code=competition_code,
            resource=ProviderResource.TEAMS,
            fetch=lambda: provider.fetch_teams(competition_external_id),
            importer=SportsIngestionService(
                self._session, provider.provider_name
            ).import_teams,
        )

    async def sync_fixtures(
        self,
        competition_code: str,
        competition_external_id: str,
        season_external_id: str,
        *,
        since: datetime | None = None,
    ) -> SportsSyncReport:
        """Fetch and ingest fixtures for one competition season."""
        provider = self._routed_provider(competition_code, ProviderResource.FIXTURES)
        return await self._execute(
            provider=provider,
            competition_code=competition_code,
            resource=ProviderResource.FIXTURES,
            fetch=lambda: provider.fetch_fixtures(
                competition_external_id,
                season_external_id,
                since=since,
            ),
            importer=SportsIngestionService(
                self._session, provider.provider_name
            ).import_fixtures,
        )

    def _routed_provider(
        self,
        competition_code: str,
        resource: ProviderResource,
    ) -> SportsDataProvider:
        candidates = self._registry.providers_for_competition(
            competition_code,
            resource=resource,
        )
        return candidates[0]

    async def _execute(
        self,
        *,
        provider: SportsDataProvider,
        competition_code: str | None,
        resource: ProviderResource,
        fetch: FetchRecords[RecordT],
        importer: ImportRecords[RecordT],
    ) -> SportsSyncReport:
        started_at = datetime.now(UTC)
        records = tuple(
            await retry_provider_call(
                fetch,
                max_attempts=self._retry_max_attempts,
                sleep=self._retry_sleep,
            )
        )
        ingestion = await importer(records)
        return SportsSyncReport(
            provider=provider.provider_name.strip().lower(),
            resource=resource,
            competition_code=(
                competition_code.strip().upper()
                if competition_code is not None
                else None
            ),
            started_at=started_at,
            completed_at=datetime.now(UTC),
            records_fetched=len(records),
            ingestion=ingestion,
        )
