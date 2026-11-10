"""Provider-neutral, transaction-safe ingestion for core sports records.

The ingestion service performs explicit upserts for competitions and teams.
It does not fetch from providers, commit transactions, or create sessions.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from chezaport.sports.domain.enums import CanonicalEntityType
from chezaport.sports.integrations.errors import ExternalIDConflictError
from chezaport.sports.integrations.schemas import (
    ProviderCompetition,
    ProviderFixture,
    ProviderSeason,
    ProviderTeam,
)
from chezaport.sports.models import Competition, Country, Fixture, Season, Sport, Team
from chezaport.sports.services.external_ids import ExternalIDResolver


def _as_utc(value: datetime) -> datetime:
    """Normalize database-returned naive timestamps and provider timestamps to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class IngestionOutcome(StrEnum):
    """Result category for one normalized provider record."""

    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class IngestionItemResult:
    """Outcome and canonical reference for one attempted provider record."""

    entity_type: CanonicalEntityType
    external_id: str
    outcome: IngestionOutcome
    canonical_id: str | None = None
    error: str | None = None


@dataclass(slots=True)
class IngestionReport:
    """Aggregate results for one import batch."""

    provider: str
    items: list[IngestionItemResult] = field(default_factory=list)

    @property
    def records_seen(self) -> int:
        return len(self.items)

    def count(self, outcome: IngestionOutcome) -> int:
        return sum(item.outcome == outcome for item in self.items)

    @property
    def created(self) -> int:
        return self.count(IngestionOutcome.CREATED)

    @property
    def updated(self) -> int:
        return self.count(IngestionOutcome.UPDATED)

    @property
    def unchanged(self) -> int:
        return self.count(IngestionOutcome.UNCHANGED)

    @property
    def failed(self) -> int:
        return self.count(IngestionOutcome.FAILED)


class SportsIngestionService:
    """Upsert normalized competition and team records into canonical tables.

    The caller owns the AsyncSession and its outer transaction. Each record is
    isolated with a database savepoint so a bad record can be reported without
    discarding successful records in the same batch. The caller must commit or
    roll back the outer transaction after inspecting the report.
    """

    def __init__(self, session: AsyncSession, provider: str) -> None:
        normalized_provider = provider.strip().lower()
        if not normalized_provider:
            raise ValueError("provider must not be blank")
        self._session = session
        self._provider = normalized_provider
        self._resolver = ExternalIDResolver(session)

    async def import_competitions(
        self, records: list[ProviderCompetition] | tuple[ProviderCompetition, ...]
    ) -> IngestionReport:
        """Create or update competition records and their provider mappings."""
        report = IngestionReport(provider=self._provider)
        await self._session.flush()
        for record in records:
            try:
                async with self._session.begin_nested():
                    result = await self._upsert_competition(record)
                report.items.append(result)
            except Exception as exc:
                report.items.append(
                    IngestionItemResult(
                        entity_type=CanonicalEntityType.COMPETITION,
                        external_id=record.external_id,
                        outcome=IngestionOutcome.FAILED,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
        return report

    async def import_teams(
        self, records: list[ProviderTeam] | tuple[ProviderTeam, ...]
    ) -> IngestionReport:
        """Create or update team records and their provider mappings."""
        report = IngestionReport(provider=self._provider)
        await self._session.flush()
        for record in records:
            try:
                async with self._session.begin_nested():
                    result = await self._upsert_team(record)
                report.items.append(result)
            except Exception as exc:
                report.items.append(
                    IngestionItemResult(
                        entity_type=CanonicalEntityType.TEAM,
                        external_id=record.external_id,
                        outcome=IngestionOutcome.FAILED,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
        return report

    async def import_seasons(
        self, records: list[ProviderSeason] | tuple[ProviderSeason, ...]
    ) -> IngestionReport:
        """Create or update seasons after their competitions have been imported."""
        report = IngestionReport(provider=self._provider)
        await self._session.flush()
        for record in records:
            try:
                async with self._session.begin_nested():
                    result = await self._upsert_season(record)
                report.items.append(result)
            except Exception as exc:
                report.items.append(
                    IngestionItemResult(
                        entity_type=CanonicalEntityType.SEASON,
                        external_id=record.external_id,
                        outcome=IngestionOutcome.FAILED,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
        return report

    async def import_fixtures(
        self, records: list[ProviderFixture] | tuple[ProviderFixture, ...]
    ) -> IngestionReport:
        """Create or update fixtures after related entities are imported."""
        report = IngestionReport(provider=self._provider)
        await self._session.flush()
        for record in records:
            try:
                async with self._session.begin_nested():
                    result = await self._upsert_fixture(record)
                report.items.append(result)
            except Exception as exc:
                report.items.append(
                    IngestionItemResult(
                        entity_type=CanonicalEntityType.FIXTURE,
                        external_id=record.external_id,
                        outcome=IngestionOutcome.FAILED,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
        return report

    async def _mapped_entity_id(
        self, entity_type: CanonicalEntityType, external_id: str
    ) -> str:
        entity_id = await self._resolver.resolve(
            provider=self._provider,
            entity_type=entity_type,
            external_id=external_id,
        )
        if entity_id is None:
            raise ValueError(
                f"unresolved {entity_type.value} provider ID: {external_id}"
            )
        return entity_id

    async def _upsert_season(self, record: ProviderSeason) -> IngestionItemResult:
        competition_id = await self._mapped_entity_id(
            CanonicalEntityType.COMPETITION, record.competition_external_id
        )
        competition = await self._session.get(Competition, competition_id)
        if competition is None:
            raise ExternalIDConflictError(
                f"mapping points to missing competition {competition_id}"
            )
        mapped_id = await self._resolver.resolve(
            provider=self._provider,
            entity_type=CanonicalEntityType.SEASON,
            external_id=record.external_id,
        )
        season = await self._session.get(Season, mapped_id) if mapped_id else None
        if mapped_id is not None and season is None:
            raise ExternalIDConflictError(f"mapping points to missing season {mapped_id}")
        if season is not None and season.competition_id != competition_id:
            raise ExternalIDConflictError("mapped season belongs to a different competition")
        if season is None:
            season = await self._session.scalar(
                select(Season).where(
                    Season.competition_id == competition_id,
                    Season.name == record.name,
                )
            )
        created = season is None
        if season is None:
            season = Season(
                competition_id=competition_id,
                name=record.name,
                start_date=record.start_date,
                end_date=record.end_date,
                is_current=record.is_current,
            )
            self._session.add(season)
            await self._session.flush()
            changed = True
        else:
            changed = any(
                (
                    season.name != record.name,
                    season.start_date != record.start_date,
                    season.end_date != record.end_date,
                    season.is_current != record.is_current,
                )
            )
            season.name = record.name
            season.start_date = record.start_date
            season.end_date = record.end_date
            season.is_current = record.is_current
            await self._session.flush()
        await self._resolver.register(
            provider=self._provider,
            entity_type=CanonicalEntityType.SEASON,
            entity_id=season.id,
            external_id=record.external_id,
        )
        return IngestionItemResult(
            entity_type=CanonicalEntityType.SEASON,
            external_id=record.external_id,
            outcome=(
                IngestionOutcome.CREATED
                if created
                else IngestionOutcome.UPDATED
                if changed
                else IngestionOutcome.UNCHANGED
            ),
            canonical_id=season.id,
        )

    async def _upsert_fixture(self, record: ProviderFixture) -> IngestionItemResult:
        competition_id = await self._mapped_entity_id(
            CanonicalEntityType.COMPETITION, record.competition_external_id
        )
        season_id = await self._mapped_entity_id(
            CanonicalEntityType.SEASON, record.season_external_id
        )
        home_team_id = await self._mapped_entity_id(
            CanonicalEntityType.TEAM, record.home_team_external_id
        )
        away_team_id = await self._mapped_entity_id(
            CanonicalEntityType.TEAM, record.away_team_external_id
        )
        season = await self._session.get(Season, season_id)
        if season is None or season.competition_id != competition_id:
            raise ValueError("fixture season does not belong to its competition")
        for team_id in (home_team_id, away_team_id):
            if await self._session.get(Team, team_id) is None:
                raise ExternalIDConflictError(f"mapping points to missing team {team_id}")

        mapped_id = await self._resolver.resolve(
            provider=self._provider,
            entity_type=CanonicalEntityType.FIXTURE,
            external_id=record.external_id,
        )
        fixture = await self._session.get(Fixture, mapped_id) if mapped_id else None
        if mapped_id is not None and fixture is None:
            raise ExternalIDConflictError(f"mapping points to missing fixture {mapped_id}")
        created = fixture is None
        values = {
            "competition_id": competition_id,
            "season_id": season_id,
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "kickoff_at": record.kickoff_at.astimezone(UTC),
            "status": record.status.value,
            "home_score": record.home_score,
            "away_score": record.away_score,
            "round_name": record.round_name,
        }
        if fixture is None:
            fixture = Fixture(**values)
            self._session.add(fixture)
            await self._session.flush()
            changed = True
        else:
            changed = any(
                (
                    _as_utc(fixture.kickoff_at) != values["kickoff_at"]
                    if key == "kickoff_at"
                    else getattr(fixture, key) != value
                )
                for key, value in values.items()
            )
            for key, value in values.items():
                setattr(fixture, key, value)
            await self._session.flush()
        await self._resolver.register(
            provider=self._provider,
            entity_type=CanonicalEntityType.FIXTURE,
            entity_id=fixture.id,
            external_id=record.external_id,
        )
        return IngestionItemResult(
            entity_type=CanonicalEntityType.FIXTURE,
            external_id=record.external_id,
            outcome=(
                IngestionOutcome.CREATED
                if created
                else IngestionOutcome.UPDATED
                if changed
                else IngestionOutcome.UNCHANGED
            ),
            canonical_id=fixture.id,
        )

    async def _sport_id(self, sport_code: str) -> str:
        sport_id = await self._session.scalar(
            select(Sport.id).where(Sport.code == sport_code.strip().lower())
        )
        if sport_id is None:
            raise ValueError(f"canonical sport is not seeded: {sport_code}")
        return sport_id

    async def _country_id(self, country_code: str | None) -> str | None:
        if country_code is None:
            return None
        country_id = await self._session.scalar(
            select(Country.id).where(Country.code == country_code.upper())
        )
        if country_id is None:
            raise ValueError(f"canonical country is not seeded: {country_code}")
        return country_id

    async def _upsert_competition(
        self, record: ProviderCompetition
    ) -> IngestionItemResult:
        sport_id = await self._sport_id(record.sport_code)
        mapped_id = await self._resolver.resolve(
            provider=self._provider,
            entity_type=CanonicalEntityType.COMPETITION,
            external_id=record.external_id,
        )
        competition = (
            await self._session.get(Competition, mapped_id) if mapped_id is not None else None
        )
        if mapped_id is not None and competition is None:
            raise ExternalIDConflictError(
                f"mapping points to missing competition {mapped_id}"
            )
        if competition is not None and competition.sport_id != sport_id:
            raise ExternalIDConflictError("mapped competition belongs to a different sport")

        if competition is None:
            competition = await self._session.scalar(
                select(Competition).where(
                    Competition.sport_id == sport_id,
                    Competition.slug == record.slug,
                )
            )
        created = competition is None
        if competition is None:
            competition = Competition(
                sport_id=sport_id,
                name=record.name,
                slug=record.slug,
                competition_type=record.competition_type,
                country_id=await self._country_id(record.country_code),
            )
            self._session.add(competition)
            await self._session.flush()
            changed = True
        else:
            country_id = (
                await self._country_id(record.country_code)
                if record.country_code is not None
                else competition.country_id
            )
            changed = any(
                (
                    competition.name != record.name,
                    competition.slug != record.slug,
                    competition.competition_type != record.competition_type,
                    competition.country_id != country_id,
                )
            )
            competition.name = record.name
            competition.slug = record.slug
            competition.competition_type = record.competition_type
            competition.country_id = country_id
            await self._session.flush()

        await self._resolver.register(
            provider=self._provider,
            entity_type=CanonicalEntityType.COMPETITION,
            entity_id=competition.id,
            external_id=record.external_id,
        )
        return IngestionItemResult(
            entity_type=CanonicalEntityType.COMPETITION,
            external_id=record.external_id,
            outcome=(
                IngestionOutcome.CREATED
                if created
                else IngestionOutcome.UPDATED
                if changed
                else IngestionOutcome.UNCHANGED
            ),
            canonical_id=competition.id,
        )

    async def _upsert_team(self, record: ProviderTeam) -> IngestionItemResult:
        sport_id = await self._sport_id(record.sport_code)
        mapped_id = await self._resolver.resolve(
            provider=self._provider,
            entity_type=CanonicalEntityType.TEAM,
            external_id=record.external_id,
        )
        team = await self._session.get(Team, mapped_id) if mapped_id is not None else None
        if mapped_id is not None and team is None:
            raise ExternalIDConflictError(f"mapping points to missing team {mapped_id}")
        if team is not None and team.sport_id != sport_id:
            raise ExternalIDConflictError("mapped team belongs to a different sport")

        if team is None:
            team = await self._session.scalar(
                select(Team).where(Team.sport_id == sport_id, Team.slug == record.slug)
            )
        created = team is None
        if team is None:
            team = Team(
                sport_id=sport_id,
                name=record.name,
                slug=record.slug,
                short_name=record.short_name,
                country_id=await self._country_id(record.country_code),
            )
            self._session.add(team)
            await self._session.flush()
            changed = True
        else:
            country_id = (
                await self._country_id(record.country_code)
                if record.country_code is not None
                else team.country_id
            )
            changed = any(
                (
                    team.name != record.name,
                    team.slug != record.slug,
                    team.short_name != record.short_name,
                    team.country_id != country_id,
                )
            )
            team.name = record.name
            team.slug = record.slug
            team.short_name = record.short_name
            team.country_id = country_id
            await self._session.flush()

        await self._resolver.register(
            provider=self._provider,
            entity_type=CanonicalEntityType.TEAM,
            entity_id=team.id,
            external_id=record.external_id,
        )
        return IngestionItemResult(
            entity_type=CanonicalEntityType.TEAM,
            external_id=record.external_id,
            outcome=(
                IngestionOutcome.CREATED
                if created
                else IngestionOutcome.UPDATED
                if changed
                else IngestionOutcome.UNCHANGED
            ),
            canonical_id=team.id,
        )
