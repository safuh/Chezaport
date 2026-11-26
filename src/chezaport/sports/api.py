"""Read-only, versioned sports API for catalog, fixtures, and analytics."""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from chezaport.sports.domain.enums import CanonicalEntityType
from chezaport.sports.integrations.errors import (
    ProviderConfigurationError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from chezaport.sports.integrations.football_data_org import FootballDataOrgProvider
from chezaport.sports.integrations.schemas import ProviderMatchDetails
from chezaport.sports.models import (
    Competition,
    Country,
    ExternalIDMapping,
    Fixture,
    FixtureMatchEvent,
    FixturePlayerParticipation,
    FixtureReportSnapshot,
    Player,
    Season,
    Sport,
    SportsSyncRun,
    Team,
    TeamMembership,
    Venue,
)
from chezaport.sports.services.analytics import (
    calculate_competition_season_comparison,
    calculate_competition_statistics,
    calculate_head_to_head,
    calculate_standings,
    calculate_team_form,
    calculate_team_season_comparison,
    calculate_team_season_statistics,
)
from chezaport.sports.services.match_report_persistence import (
    replace_canonical_fixture_report,
)

router = APIRouter(tags=["sports"])


async def _session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.db_session_factory
    async with factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(_session)]


class SyncRunRead(BaseModel):
    id: str
    provider: str
    resource: str
    competition_code: str | None
    status: str
    started_at: datetime
    completed_at: datetime | None
    records_fetched: int
    records_seen: int
    created: int
    updated: int
    unchanged: int
    failed: int
    error_summary: str | None
    duration_seconds: float | None


class SyncRunPage(BaseModel):
    items: list[SyncRunRead]
    total: int
    limit: int
    offset: int


class SyncFreshnessRead(BaseModel):
    provider: str
    resource: str
    last_status: str
    last_started_at: datetime
    last_completed_at: datetime | None
    age_seconds: float | None
    is_stale: bool


@router.get("/ops/data-quality")
async def get_data_quality(session: SessionDep) -> dict[str, object]:
    """Report measurable integrity issues in canonical sports records.

    Counts are intentionally read-only and avoid exposing provider payloads or
    personal data. A clean result means these checks found no anomalies; it is
    not a claim that every source record has been independently verified.
    """
    mapping_targets: dict[str, Any] = {
        "sport": Sport,
        "country": Country,
        "venue": Venue,
        "competition": Competition,
        "season": Season,
        "team": Team,
        "player": Player,
        "fixture": Fixture,
    }
    orphan_mapping_conditions = [
        (
            (ExternalIDMapping.entity_type == entity_type)
            & ~select(model.id).where(model.id == ExternalIDMapping.entity_id).exists()
        )
        for entity_type, model in mapping_targets.items()
    ]
    orphan_mappings = int(
        await session.scalar(
            select(func.count())
            .select_from(ExternalIDMapping)
            .where(or_(*orphan_mapping_conditions))
        )
        or 0
    )
    finished_missing_score = int(
        await session.scalar(
            select(func.count())
            .select_from(Fixture)
            .where(
                Fixture.status == "finished",
                or_(Fixture.home_score.is_(None), Fixture.away_score.is_(None)),
            )
        )
        or 0
    )
    partial_score = int(
        await session.scalar(
            select(func.count())
            .select_from(Fixture)
            .where(
                or_(
                    (Fixture.home_score.is_(None) & Fixture.away_score.is_not(None)),
                    (Fixture.home_score.is_not(None) & Fixture.away_score.is_(None)),
                )
            )
        )
        or 0
    )
    past_scheduled_fixtures = int(
        await session.scalar(
            select(func.count())
            .select_from(Fixture)
            .where(
                Fixture.status == "scheduled",
                Fixture.kickoff_at < datetime.now(UTC),
            )
        )
        or 0
    )
    home_team = aliased(Team)
    away_team = aliased(Team)
    participant_sport_mismatch = int(
        await session.scalar(
            select(func.count())
            .select_from(Fixture)
            .join(Competition, Fixture.competition_id == Competition.id)
            .join(home_team, Fixture.home_team_id == home_team.id)
            .join(away_team, Fixture.away_team_id == away_team.id)
            .where(
                or_(
                    home_team.sport_id != Competition.sport_id,
                    away_team.sport_id != Competition.sport_id,
                )
            )
        )
        or 0
    )
    season_mismatch = int(
        await session.scalar(
            select(func.count())
            .select_from(Fixture)
            .join(Season, Fixture.season_id == Season.id)
            .where(Fixture.competition_id != Season.competition_id)
        )
        or 0
    )
    competition_mapping = aliased(ExternalIDMapping)
    fixture_mapping = aliased(ExternalIDMapping)
    unmapped_provider_fixtures = int(
        await session.scalar(
            select(func.count())
            .select_from(Fixture)
            .where(
                select(1)
                .select_from(competition_mapping)
                .where(
                    competition_mapping.entity_type == "competition",
                    competition_mapping.entity_id == Fixture.competition_id,
                    ~select(1)
                    .select_from(fixture_mapping)
                    .where(
                        fixture_mapping.provider == competition_mapping.provider,
                        fixture_mapping.entity_type == "fixture",
                        fixture_mapping.entity_id == Fixture.id,
                    )
                    .exists(),
                )
                .exists()
            )
        )
        or 0
    )
    expected_team_mappings = (
        select(competition_mapping.provider.label("provider"), Team.id.label("entity_id"))
        .select_from(competition_mapping)
        .join(Competition, Competition.id == competition_mapping.entity_id)
        .join(Fixture, Fixture.competition_id == Competition.id)
        .join(Team, or_(Team.id == Fixture.home_team_id, Team.id == Fixture.away_team_id))
        .where(competition_mapping.entity_type == "competition")
        .distinct()
        .subquery()
    )
    missing_provider_teams = int(
        await session.scalar(
            select(func.count())
            .select_from(expected_team_mappings)
            .where(
                ~select(1)
                .select_from(ExternalIDMapping)
                .where(
                    ExternalIDMapping.provider == expected_team_mappings.c.provider,
                    ExternalIDMapping.entity_type == "team",
                    ExternalIDMapping.entity_id == expected_team_mappings.c.entity_id,
                )
                .exists()
            )
        )
        or 0
    )
    expected_season_mappings = (
        select(competition_mapping.provider.label("provider"), Season.id.label("entity_id"))
        .select_from(competition_mapping)
        .join(Competition, Competition.id == competition_mapping.entity_id)
        .join(Season, Season.competition_id == Competition.id)
        .where(competition_mapping.entity_type == "competition")
        .distinct()
        .subquery()
    )
    missing_provider_seasons = int(
        await session.scalar(
            select(func.count())
            .select_from(expected_season_mappings)
            .where(
                ~select(1)
                .select_from(ExternalIDMapping)
                .where(
                    ExternalIDMapping.provider == expected_season_mappings.c.provider,
                    ExternalIDMapping.entity_type == "season",
                    ExternalIDMapping.entity_id == expected_season_mappings.c.entity_id,
                )
                .exists()
            )
        )
        or 0
    )
    checks = [
        {"code": "finished_fixture_missing_score", "count": finished_missing_score},
        {"code": "fixture_partial_score", "count": partial_score},
        {"code": "fixture_past_kickoff_still_scheduled", "count": past_scheduled_fixtures},
        {"code": "fixture_season_competition_mismatch", "count": season_mismatch},
        {"code": "fixture_participant_sport_mismatch", "count": participant_sport_mismatch},
        {"code": "orphan_external_id_mapping", "count": orphan_mappings},
        {
            "code": "provider_fixture_missing_mapping",
            "count": unmapped_provider_fixtures,
        },
        {"code": "provider_team_missing_mapping", "count": missing_provider_teams},
        {"code": "provider_season_missing_mapping", "count": missing_provider_seasons},
    ]
    total_issues = (
        finished_missing_score
        + partial_score
        + past_scheduled_fixtures
        + season_mismatch
        + participant_sport_mismatch
        + orphan_mappings
        + unmapped_provider_fixtures
        + missing_provider_teams
        + missing_provider_seasons
    )
    return {
        "status": "healthy" if total_issues == 0 else "degraded",
        "total_issues": total_issues,
        "checks": checks,
        "generated_at": datetime.now(UTC),
        "scope": "canonical database integrity checks; not source verification",
    }


@router.get("/ops/data-quality/issues")
async def list_data_quality_issues(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    """Return paginated, actionable references for detected integrity issues."""
    report = await get_data_quality(session)
    page_size = limit + offset
    found: list[dict[str, str | None]] = []

    async def collect(
        statement: Any,
        code: str,
        entity_type: str,
        description: str,
    ) -> None:
        rows = (await session.execute(statement.limit(page_size))).mappings().all()
        found.extend(
            {
                "code": code,
                "entity_type": entity_type,
                "entity_id": str(row["entity_id"]),
                "provider": row.get("provider"),
                "description": description,
            }
            for row in rows
        )

    home_team = aliased(Team)
    away_team = aliased(Team)
    await collect(
        select(Fixture.id.label("entity_id"), literal(None).label("provider"))
        .where(
            Fixture.status == "finished",
            or_(Fixture.home_score.is_(None), Fixture.away_score.is_(None)),
        )
        .order_by(Fixture.id),
        "finished_fixture_missing_score",
        "fixture",
        "Fixture is finished but one or both scores are missing.",
    )
    await collect(
        select(Fixture.id.label("entity_id"), literal(None).label("provider"))
        .where(
            or_(
                (Fixture.home_score.is_(None) & Fixture.away_score.is_not(None)),
                (Fixture.home_score.is_not(None) & Fixture.away_score.is_(None)),
            )
        )
        .order_by(Fixture.id),
        "fixture_partial_score",
        "fixture",
        "Only one side of the fixture score is populated.",
    )
    await collect(
        select(Fixture.id.label("entity_id"), literal(None).label("provider"))
        .where(
            Fixture.status == "scheduled",
            Fixture.kickoff_at < datetime.now(UTC),
        )
        .order_by(Fixture.id),
        "fixture_past_kickoff_still_scheduled",
        "fixture",
        "Kick-off time has passed but the fixture is still marked scheduled.",
    )
    await collect(
        select(Fixture.id.label("entity_id"), literal(None).label("provider"))
        .join(Season, Fixture.season_id == Season.id)
        .where(Fixture.competition_id != Season.competition_id)
        .order_by(Fixture.id),
        "fixture_season_competition_mismatch",
        "fixture",
        "Fixture competition does not match its season competition.",
    )
    await collect(
        select(Fixture.id.label("entity_id"), literal(None).label("provider"))
        .join(Competition, Fixture.competition_id == Competition.id)
        .join(home_team, Fixture.home_team_id == home_team.id)
        .join(away_team, Fixture.away_team_id == away_team.id)
        .where(
            or_(
                home_team.sport_id != Competition.sport_id,
                away_team.sport_id != Competition.sport_id,
            )
        )
        .order_by(Fixture.id),
        "fixture_participant_sport_mismatch",
        "fixture",
        "A participating team belongs to a different sport from the competition.",
    )

    mapping_targets: dict[str, Any] = {
        "sport": Sport,
        "country": Country,
        "venue": Venue,
        "competition": Competition,
        "season": Season,
        "team": Team,
        "player": Player,
        "fixture": Fixture,
    }
    for entity_type, model in mapping_targets.items():
        await collect(
            select(
                ExternalIDMapping.entity_id.label("entity_id"),
                ExternalIDMapping.provider.label("provider"),
            )
            .where(
                ExternalIDMapping.entity_type == entity_type,
                ~select(model.id).where(model.id == ExternalIDMapping.entity_id).exists(),
            )
            .order_by(ExternalIDMapping.entity_id, ExternalIDMapping.provider),
            "orphan_external_id_mapping",
            entity_type,
            "Provider mapping points to a canonical record that no longer exists.",
        )

    competition_mapping = aliased(ExternalIDMapping)
    fixture_mapping = aliased(ExternalIDMapping)
    missing_fixture_mapping = (
        select(
            Fixture.id.label("entity_id"),
            competition_mapping.provider.label("provider"),
        )
        .join(competition_mapping, competition_mapping.entity_type == "competition")
        .where(
            competition_mapping.entity_id == Fixture.competition_id,
            ~select(1)
            .select_from(fixture_mapping)
            .where(
                fixture_mapping.provider == competition_mapping.provider,
                fixture_mapping.entity_type == "fixture",
                fixture_mapping.entity_id == Fixture.id,
            )
            .exists(),
        )
        .order_by(Fixture.id, competition_mapping.provider)
    )
    await collect(
        missing_fixture_mapping,
        "provider_fixture_missing_mapping",
        "fixture",
        "Fixture belongs to a provider-backed competition but has no mapping for that provider.",
    )

    expected_team_mappings = (
        select(competition_mapping.provider.label("provider"), Team.id.label("entity_id"))
        .select_from(competition_mapping)
        .join(Competition, Competition.id == competition_mapping.entity_id)
        .join(Fixture, Fixture.competition_id == Competition.id)
        .join(Team, or_(Team.id == Fixture.home_team_id, Team.id == Fixture.away_team_id))
        .where(competition_mapping.entity_type == "competition")
        .distinct()
        .subquery()
    )
    await collect(
        select(
            expected_team_mappings.c.entity_id,
            expected_team_mappings.c.provider,
        )
        .where(
            ~select(1)
            .select_from(ExternalIDMapping)
            .where(
                ExternalIDMapping.provider == expected_team_mappings.c.provider,
                ExternalIDMapping.entity_type == "team",
                ExternalIDMapping.entity_id == expected_team_mappings.c.entity_id,
            )
            .exists()
        )
        .order_by(expected_team_mappings.c.entity_id, expected_team_mappings.c.provider),
        "provider_team_missing_mapping",
        "team",
        "Team participates in a provider-backed competition but has no mapping for that provider.",
    )

    expected_season_mappings = (
        select(competition_mapping.provider.label("provider"), Season.id.label("entity_id"))
        .select_from(competition_mapping)
        .join(Competition, Competition.id == competition_mapping.entity_id)
        .join(Season, Season.competition_id == Competition.id)
        .where(competition_mapping.entity_type == "competition")
        .distinct()
        .subquery()
    )
    await collect(
        select(
            expected_season_mappings.c.entity_id,
            expected_season_mappings.c.provider,
        )
        .where(
            ~select(1)
            .select_from(ExternalIDMapping)
            .where(
                ExternalIDMapping.provider == expected_season_mappings.c.provider,
                ExternalIDMapping.entity_type == "season",
                ExternalIDMapping.entity_id == expected_season_mappings.c.entity_id,
            )
            .exists()
        )
        .order_by(expected_season_mappings.c.entity_id, expected_season_mappings.c.provider),
        "provider_season_missing_mapping",
        "season",
        "Season belongs to a provider-backed competition but has no mapping for that provider.",
    )

    found.sort(
        key=lambda item: (item["code"] or "", item["entity_id"] or "", item["provider"] or "")
    )
    total_issues = report.get("total_issues", 0)
    return {
        "items": found[offset : offset + limit],
        "total": total_issues if isinstance(total_issues, int) else 0,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/ops/sync-runs",
    response_model=SyncRunPage,
)
async def list_sync_runs(
    session: SessionDep,
    provider: str | None = Query(default=None, max_length=80),
    resource: str | None = Query(default=None, max_length=32),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern="^(running|succeeded|partial|failed)$",
    ),
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SyncRunPage:
    """List recent sync attempts; contains read-only, non-secret operational metadata."""
    statement = select(SportsSyncRun)
    if provider:
        statement = statement.where(SportsSyncRun.provider == provider.strip().lower())
    if resource:
        statement = statement.where(SportsSyncRun.resource == resource.strip().lower())
    if status_filter:
        statement = statement.where(SportsSyncRun.status == status_filter)
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = await session.scalars(
        statement.order_by(SportsSyncRun.started_at.desc(), SportsSyncRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    items: list[SyncRunRead] = []
    for run in rows.all():
        duration = None
        if run.completed_at is not None:
            start = run.started_at
            end = run.completed_at
            if start.tzinfo is None:
                start = start.replace(tzinfo=UTC)
            if end.tzinfo is None:
                end = end.replace(tzinfo=UTC)
            duration = max(0.0, (end - start).total_seconds())
        items.append(
            SyncRunRead(
                id=run.id,
                provider=run.provider,
                resource=run.resource,
                competition_code=run.competition_code,
                status=run.status,
                started_at=run.started_at,
                completed_at=run.completed_at,
                records_fetched=run.records_fetched,
                records_seen=run.records_seen,
                created=run.created,
                updated=run.updated,
                unchanged=run.unchanged,
                failed=run.failed,
                error_summary=run.error_summary,
                duration_seconds=duration,
            )
        )
    return SyncRunPage(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/ops/sync-freshness",
    response_model=list[SyncFreshnessRead],
)
async def get_sync_freshness(
    session: SessionDep,
    stale_after_seconds: Annotated[int, Query(ge=60, le=604800)] = 86400,
) -> list[SyncFreshnessRead]:
    """Summarize latest provider/resource attempts for the public data-status display."""
    ranked_runs = select(
        SportsSyncRun.id.label("run_id"),
        func.row_number()
        .over(
            partition_by=(SportsSyncRun.provider, SportsSyncRun.resource),
            order_by=(SportsSyncRun.started_at.desc(), SportsSyncRun.id.desc()),
        )
        .label("position"),
    ).subquery()
    rows = await session.scalars(
        select(SportsSyncRun)
        .join(ranked_runs, ranked_runs.c.run_id == SportsSyncRun.id)
        .where(ranked_runs.c.position == 1)
        .order_by(SportsSyncRun.provider.asc(), SportsSyncRun.resource.asc())
    )
    now = datetime.now(UTC)
    result: list[SyncFreshnessRead] = []
    for run in rows.all():
        provider, resource = run.provider, run.resource
        timestamp = run.completed_at or run.started_at
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        age = max(0.0, (now - timestamp).total_seconds())
        result.append(
            SyncFreshnessRead(
                provider=provider,
                resource=resource,
                last_status=run.status,
                last_started_at=run.started_at,
                last_completed_at=run.completed_at,
                age_seconds=age,
                is_stale=run.status != "succeeded" or age > stale_after_seconds,
            )
        )
    return result


class SportRead(BaseModel):
    id: str
    code: str
    name: str
    is_active: bool


class CompetitionRead(BaseModel):
    id: str
    sport_id: str
    country_id: str | None
    name: str
    slug: str
    competition_type: str
    is_active: bool


class FixtureRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    competition_id: str
    season_id: str
    home_team_id: str
    home_team_name: str
    away_team_id: str
    away_team_name: str
    kickoff_at: datetime
    status: str
    home_score: int | None
    away_score: int | None
    round_name: str | None


class FixturePage(BaseModel):
    items: list[FixtureRead]
    total: int
    limit: int
    offset: int


class FixtureDetailRead(FixtureRead):
    competition_name: str
    season_name: str
    venue_id: str | None
    venue_name: str | None
    venue_city: str | None


class CountryRead(BaseModel):
    id: str
    code: str | None
    name: str


class CountryPage(BaseModel):
    items: list[CountryRead]
    total: int
    limit: int
    offset: int


class VenueRead(BaseModel):
    id: str
    name: str
    city: str | None
    country_id: str | None
    capacity: int | None


class VenuePage(BaseModel):
    items: list[VenueRead]
    total: int
    limit: int
    offset: int


class TeamRead(BaseModel):
    id: str
    sport_id: str
    country_id: str | None
    venue_id: str | None
    name: str
    slug: str
    short_name: str | None
    founded_year: int | None
    is_active: bool


class TeamPage(BaseModel):
    items: list[TeamRead]
    total: int
    limit: int
    offset: int


class TeamDetailRead(TeamRead):
    country_name: str | None
    venue_name: str | None
    venue_city: str | None
    venue_capacity: int | None


class SeasonRead(BaseModel):
    id: str
    competition_id: str
    name: str
    start_date: date | None
    end_date: date | None
    is_current: bool


class SeasonPage(BaseModel):
    items: list[SeasonRead]
    total: int
    limit: int
    offset: int


class PlayerRead(BaseModel):
    id: str
    country_id: str | None
    first_name: str | None
    last_name: str | None
    display_name: str
    date_of_birth: date | None
    position: str | None


class PlayerPage(BaseModel):
    items: list[PlayerRead]
    total: int
    limit: int
    offset: int


class PlayerMembershipRead(BaseModel):
    membership_id: str
    team_id: str
    team_name: str
    joined_on: date | None
    left_on: date | None
    shirt_number: int | None


class PlayerDetailRead(PlayerRead):
    memberships: list[PlayerMembershipRead]


class PlayerStatisticsRead(BaseModel):
    player_id: str
    competition_id: str | None
    season_id: str | None
    provider: str
    provider_identity_linked: bool
    fixtures_with_reports: int
    appearances: int
    starts: int
    goals: int
    assists: int
    yellow_cards: int
    red_cards: int
    substitutions_in: int
    substitutions_out: int
    minutes_played: int | None = None
    minutes_unavailable_reason: str | None = None


class SquadMemberRead(PlayerRead):
    membership_id: str
    joined_on: date | None
    left_on: date | None
    shirt_number: int | None


class SquadRead(BaseModel):
    team_id: str
    as_of: date
    items: list[SquadMemberRead]
    total: int


@router.get("/sports", response_model=list[SportRead])
async def list_sports(session: SessionDep) -> list[Sport]:
    """List active sports in the canonical catalogue."""
    result = await session.scalars(
        select(Sport).where(Sport.is_active.is_(True)).order_by(Sport.name.asc())
    )
    return list(result.all())


@router.get("/competitions", response_model=list[CompetitionRead])
async def list_competitions(
    session: SessionDep,
    sport_id: str | None = None,
    active_only: bool = True,
) -> list[Competition]:
    """List competitions, optionally restricted to one canonical sport."""
    statement = select(Competition).order_by(Competition.name.asc())
    if sport_id is not None:
        statement = statement.where(Competition.sport_id == sport_id)
    if active_only:
        statement = statement.where(Competition.is_active.is_(True))
    result = await session.scalars(statement)
    return list(result.all())


@router.get("/countries", response_model=CountryPage)
async def list_countries(
    session: SessionDep,
    search: str | None = Query(default=None, max_length=120),
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CountryPage:
    """List countries and territories in the canonical catalogue."""
    statement = select(Country)
    if search is not None and search.strip():
        pattern = f"%{search.strip()}%"
        statement = statement.where(or_(Country.name.ilike(pattern), Country.code.ilike(pattern)))
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = await session.scalars(
        statement.order_by(Country.name.asc(), Country.id.asc()).limit(limit).offset(offset)
    )
    items = [CountryRead.model_validate(row, from_attributes=True) for row in rows.all()]
    return CountryPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/venues", response_model=VenuePage)
async def list_venues(
    session: SessionDep,
    country_id: str | None = None,
    search: str | None = Query(default=None, max_length=160),
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> VenuePage:
    """List stadiums and venues, optionally filtered by country or name."""
    statement = select(Venue)
    if country_id is not None:
        statement = statement.where(Venue.country_id == country_id)
    if search is not None and search.strip():
        pattern = f"%{search.strip()}%"
        statement = statement.where(or_(Venue.name.ilike(pattern), Venue.city.ilike(pattern)))
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = await session.scalars(
        statement.order_by(Venue.name.asc(), Venue.id.asc()).limit(limit).offset(offset)
    )
    items = [VenueRead.model_validate(row, from_attributes=True) for row in rows.all()]
    return VenuePage(items=items, total=total, limit=limit, offset=offset)


@router.get("/teams", response_model=TeamPage)
async def list_teams(
    session: SessionDep,
    sport_id: str | None = None,
    country_id: str | None = None,
    competition_id: str | None = None,
    season_id: str | None = None,
    active_only: bool = True,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TeamPage:
    """List canonical teams with optional competition/season membership filters."""
    statement = select(Team)
    if sport_id is not None:
        statement = statement.where(Team.sport_id == sport_id)
    if country_id is not None:
        statement = statement.where(Team.country_id == country_id)
    if active_only:
        statement = statement.where(Team.is_active.is_(True))
    if competition_id is not None or season_id is not None:
        home_ids = select(Fixture.home_team_id)
        away_ids = select(Fixture.away_team_id)
        if competition_id is not None:
            home_ids = home_ids.where(Fixture.competition_id == competition_id)
            away_ids = away_ids.where(Fixture.competition_id == competition_id)
        if season_id is not None:
            home_ids = home_ids.where(Fixture.season_id == season_id)
            away_ids = away_ids.where(Fixture.season_id == season_id)
        statement = statement.where(Team.id.in_(home_ids.union(away_ids)))
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = await session.scalars(
        statement.order_by(Team.name.asc(), Team.id.asc()).limit(limit).offset(offset)
    )
    items = [TeamRead.model_validate(row, from_attributes=True) for row in rows.all()]
    return TeamPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/teams/{team_id}", response_model=TeamDetailRead)
async def get_team(team_id: str, session: SessionDep) -> TeamDetailRead:
    """Return canonical club identity and home-ground context."""
    row = (
        await session.execute(
            select(Team, Country.name, Venue.name, Venue.city, Venue.capacity)
            .outerjoin(Country, Team.country_id == Country.id)
            .outerjoin(Venue, Team.venue_id == Venue.id)
            .where(Team.id == team_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Team not found")
    team, country_name, venue_name, venue_city, venue_capacity = row
    return TeamDetailRead(
        id=team.id,
        sport_id=team.sport_id,
        country_id=team.country_id,
        venue_id=team.venue_id,
        name=team.name,
        slug=team.slug,
        short_name=team.short_name,
        founded_year=team.founded_year,
        is_active=team.is_active,
        country_name=country_name,
        venue_name=venue_name,
        venue_city=venue_city,
        venue_capacity=venue_capacity,
    )


@router.get("/seasons", response_model=SeasonPage)
async def list_seasons(
    session: SessionDep,
    competition_id: str | None = None,
    current_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SeasonPage:
    """List competition seasons, optionally restricted to current editions."""
    statement = select(Season)
    if competition_id is not None:
        statement = statement.where(Season.competition_id == competition_id)
    if current_only:
        statement = statement.where(Season.is_current.is_(True))
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = await session.scalars(
        statement.order_by(Season.start_date.desc(), Season.name.desc(), Season.id.asc())
        .limit(limit)
        .offset(offset)
    )
    items = [SeasonRead.model_validate(row, from_attributes=True) for row in rows.all()]
    return SeasonPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/players", response_model=PlayerPage)
async def list_players(
    session: SessionDep,
    country_id: str | None = None,
    position: str | None = Query(default=None, max_length=40),
    search: str | None = Query(default=None, max_length=100),
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PlayerPage:
    """Search canonical player profiles by nationality, position, or name."""
    statement = select(Player)
    if country_id is not None:
        statement = statement.where(Player.country_id == country_id)
    if position is not None and position.strip():
        statement = statement.where(func.lower(Player.position) == position.strip().lower())
    if search is not None and search.strip():
        pattern = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                Player.display_name.ilike(pattern),
                Player.first_name.ilike(pattern),
                Player.last_name.ilike(pattern),
            )
        )
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    rows = await session.scalars(
        statement.order_by(Player.display_name.asc(), Player.id.asc()).limit(limit).offset(offset)
    )
    items = [PlayerRead.model_validate(row, from_attributes=True) for row in rows.all()]
    return PlayerPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/players/{player_id}", response_model=PlayerDetailRead)
async def get_player(player_id: str, session: SessionDep) -> PlayerDetailRead:
    """Return a player profile and its full team-registration history."""
    player = await session.get(Player, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")
    rows = await session.execute(
        select(TeamMembership, Team.name)
        .join(Team, TeamMembership.team_id == Team.id)
        .where(TeamMembership.player_id == player_id)
        .order_by(TeamMembership.joined_on.desc(), Team.name.asc())
    )
    memberships = [
        PlayerMembershipRead(
            membership_id=membership.id,
            team_id=membership.team_id,
            team_name=team_name,
            joined_on=membership.joined_on,
            left_on=membership.left_on,
            shirt_number=membership.shirt_number,
        )
        for membership, team_name in rows.all()
    ]
    return PlayerDetailRead(
        id=player.id,
        country_id=player.country_id,
        first_name=player.first_name,
        last_name=player.last_name,
        display_name=player.display_name,
        date_of_birth=player.date_of_birth,
        position=player.position,
        memberships=memberships,
    )


@router.get("/players/{player_id}/statistics", response_model=PlayerStatisticsRead)
async def get_player_statistics(
    player_id: str,
    session: SessionDep,
    competition_id: str | None = None,
    season_id: str | None = None,
) -> PlayerStatisticsRead:
    """Aggregate only provider-confirmed player events and appearances.

    Minutes are intentionally unavailable until the source supplies reliable
    on/off-pitch timing; a starting lineup alone cannot establish playing time.
    """
    player = await session.get(Player, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found")
    if season_id is not None:
        season = await session.get(Season, season_id)
        if season is None or (competition_id and season.competition_id != competition_id):
            raise HTTPException(status_code=404, detail="Competition season not found")
        competition_id = season.competition_id

    provider = "football-data-org"
    identity = await session.scalar(
        select(ExternalIDMapping).where(
            ExternalIDMapping.provider == provider,
            ExternalIDMapping.entity_type == CanonicalEntityType.PLAYER.value,
            ExternalIDMapping.entity_id == player_id,
        )
    )
    fixture_statement = select(Fixture.id)
    if competition_id is not None:
        fixture_statement = fixture_statement.where(Fixture.competition_id == competition_id)
    if season_id is not None:
        fixture_statement = fixture_statement.where(Fixture.season_id == season_id)
    fixture_ids = list((await session.scalars(fixture_statement)).all())
    snapshots = []
    if fixture_ids:
        snapshots = list(
            (
                await session.scalars(
                    select(FixtureReportSnapshot).where(
                        FixtureReportSnapshot.provider == provider,
                        FixtureReportSnapshot.fixture_id.in_(fixture_ids),
                    )
                )
            ).all()
        )

    appearances = starts = 0
    goals = assists = yellow_cards = red_cards = substitutions_in = substitutions_out = 0
    if identity is not None and fixture_ids:
        # Backfill canonical rows from reports cached before this schema existed.
        backfilled = False
        for snapshot in snapshots:
            existing = await session.scalar(
                select(FixtureMatchEvent.id).where(
                    FixtureMatchEvent.provider == provider,
                    FixtureMatchEvent.fixture_id == snapshot.fixture_id,
                ).limit(1)
            )
            participation_exists = await session.scalar(
                select(FixturePlayerParticipation.id).where(
                    FixturePlayerParticipation.provider == provider,
                    FixturePlayerParticipation.fixture_id == snapshot.fixture_id,
                ).limit(1)
            )
            if existing is None and participation_exists is None:
                cached_report = ProviderMatchDetails.model_validate(snapshot.payload)
                await replace_canonical_fixture_report(
                    session,
                    provider=provider,
                    fixture_id=snapshot.fixture_id,
                    report=cached_report,
                )
                backfilled = True
        if backfilled:
            await session.flush()
        event_rows = list(
            (
                await session.scalars(
                    select(FixtureMatchEvent).where(
                        FixtureMatchEvent.provider == provider,
                        FixtureMatchEvent.fixture_id.in_(fixture_ids),
                    )
                )
            ).all()
        )
        participation_rows = list(
            (
                await session.scalars(
                    select(FixturePlayerParticipation).where(
                        FixturePlayerParticipation.provider == provider,
                        FixturePlayerParticipation.fixture_id.in_(fixture_ids),
                        FixturePlayerParticipation.player_external_id == identity.external_id,
                    )
                )
            ).all()
        )
        appearances = len({row.fixture_id for row in participation_rows if row.appeared})
        starts = len({row.fixture_id for row in participation_rows if row.is_starter})
        for event in event_rows:
            payload = event.payload
            if event.event_type == "goal":
                goals += event.player_external_id == identity.external_id
                assists += event.secondary_player_external_id == identity.external_id
            elif event.event_type == "booking" and event.player_external_id == identity.external_id:
                card = str(payload.get("card", "")).lower()
                yellow_cards += "yellow" in card
                red_cards += "red" in card
            elif event.event_type == "substitution":
                substitutions_in += event.player_external_id == identity.external_id
                substitutions_out += event.secondary_player_external_id == identity.external_id

    return PlayerStatisticsRead(
        player_id=player_id,
        competition_id=competition_id,
        season_id=season_id,
        provider=provider,
        provider_identity_linked=identity is not None,
        fixtures_with_reports=len(snapshots),
        appearances=appearances,
        starts=starts,
        goals=goals,
        assists=assists,
        yellow_cards=yellow_cards,
        red_cards=red_cards,
        substitutions_in=substitutions_in,
        substitutions_out=substitutions_out,
        minutes_played=None,
        minutes_unavailable_reason=(
            "The provider report does not supply reliable player on/off-pitch timestamps."
        ),
    )


@router.get("/teams/{team_id}/squad", response_model=SquadRead)
async def team_squad(
    team_id: str,
    session: SessionDep,
    as_of: date | None = None,
) -> SquadRead:
    """Return registrations active on a date, preserving historical transfers."""
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    effective_date = as_of or date.today()
    statement = (
        select(Player, TeamMembership)
        .join(TeamMembership, TeamMembership.player_id == Player.id)
        .where(
            TeamMembership.team_id == team_id,
            or_(TeamMembership.joined_on.is_(None), TeamMembership.joined_on <= effective_date),
            or_(TeamMembership.left_on.is_(None), TeamMembership.left_on >= effective_date),
        )
        .order_by(TeamMembership.shirt_number.asc().nulls_last(), Player.display_name.asc())
    )
    rows = (await session.execute(statement)).all()
    items = [
        SquadMemberRead(
            id=player.id,
            country_id=player.country_id,
            first_name=player.first_name,
            last_name=player.last_name,
            display_name=player.display_name,
            date_of_birth=player.date_of_birth,
            position=player.position,
            membership_id=membership.id,
            joined_on=membership.joined_on,
            left_on=membership.left_on,
            shirt_number=membership.shirt_number,
        )
        for player, membership in rows
    ]
    return SquadRead(team_id=team_id, as_of=effective_date, items=items, total=len(items))


@router.get("/fixtures", response_model=FixturePage)
async def list_fixtures(
    session: SessionDep,
    competition_id: str | None = None,
    season_id: str | None = None,
    team_id: str | None = None,
    fixture_status: str | None = Query(default=None, alias="status"),
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FixturePage:
    """Browse fixtures with stable ordering and bounded offset pagination."""
    if from_date is not None and to_date is not None and to_date < from_date:
        raise HTTPException(status_code=422, detail="to_date must not precede from_date")
    statement = select(Fixture)
    if competition_id is not None:
        statement = statement.where(Fixture.competition_id == competition_id)
    if season_id is not None:
        statement = statement.where(Fixture.season_id == season_id)
    if team_id is not None:
        statement = statement.where(
            (Fixture.home_team_id == team_id) | (Fixture.away_team_id == team_id)
        )
    if fixture_status is not None:
        statement = statement.where(Fixture.status == fixture_status)
    if from_date is not None:
        statement = statement.where(Fixture.kickoff_at >= from_date)
    if to_date is not None:
        statement = statement.where(Fixture.kickoff_at <= to_date)

    count_statement = select(func.count()).select_from(statement.subquery())
    total = int(await session.scalar(count_statement) or 0)
    home = aliased(Team)
    away = aliased(Team)
    page_statement = (
        select(Fixture, home.name, away.name)
        .join(home, Fixture.home_team_id == home.id)
        .join(away, Fixture.away_team_id == away.id)
        .where(Fixture.id.in_(statement.with_only_columns(Fixture.id).order_by(None)))
        .order_by(Fixture.kickoff_at.asc(), Fixture.id.asc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(page_statement)).all()
    items = [
        FixtureRead(
            id=fixture.id,
            competition_id=fixture.competition_id,
            season_id=fixture.season_id,
            home_team_id=fixture.home_team_id,
            home_team_name=home_name,
            away_team_id=fixture.away_team_id,
            away_team_name=away_name,
            kickoff_at=fixture.kickoff_at,
            status=fixture.status,
            home_score=fixture.home_score,
            away_score=fixture.away_score,
            round_name=fixture.round_name,
        )
        for fixture, home_name, away_name in rows
    ]
    return FixturePage(items=items, total=total, limit=limit, offset=offset)


@router.get("/fixtures/{fixture_id}", response_model=FixtureDetailRead)
async def get_fixture(fixture_id: str, session: SessionDep) -> FixtureDetailRead:
    """Return a fixture with competition, season, team, and venue context."""
    home = aliased(Team)
    away = aliased(Team)
    row = (
        await session.execute(
            select(
                Fixture,
                home.name,
                away.name,
                Competition.name,
                Season.name,
                Venue.id,
                Venue.name,
                Venue.city,
            )
            .join(home, Fixture.home_team_id == home.id)
            .join(away, Fixture.away_team_id == away.id)
            .join(Competition, Fixture.competition_id == Competition.id)
            .join(Season, Fixture.season_id == Season.id)
            .outerjoin(Venue, Fixture.venue_id == Venue.id)
            .where(Fixture.id == fixture_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Fixture not found")
    (
        fixture,
        home_name,
        away_name,
        competition_name,
        season_name,
        venue_id,
        venue_name,
        venue_city,
    ) = row
    return FixtureDetailRead(
        id=fixture.id,
        competition_id=fixture.competition_id,
        season_id=fixture.season_id,
        home_team_id=fixture.home_team_id,
        home_team_name=home_name,
        away_team_id=fixture.away_team_id,
        away_team_name=away_name,
        kickoff_at=fixture.kickoff_at,
        status=fixture.status,
        home_score=fixture.home_score,
        away_score=fixture.away_score,
        round_name=fixture.round_name,
        competition_name=competition_name,
        season_name=season_name,
        venue_id=venue_id,
        venue_name=venue_name,
        venue_city=venue_city,
    )


@router.get("/fixtures/{fixture_id}/report", response_model=ProviderMatchDetails)
async def get_fixture_report(
    fixture_id: str,
    request: Request,
    session: SessionDep,
    refresh: bool = Query(default=False),
) -> ProviderMatchDetails:
    """Return a cached normalized report, refreshing stale data on demand."""
    fixture = await session.get(Fixture, fixture_id)
    if fixture is None:
        raise HTTPException(status_code=404, detail="Fixture not found")
    provider_name = "football-data-org"
    snapshot = await session.scalar(
        select(FixtureReportSnapshot).where(
            FixtureReportSnapshot.provider == provider_name,
            FixtureReportSnapshot.fixture_id == fixture_id,
        )
    )
    now = datetime.now(UTC)
    if snapshot is not None and not refresh:
        fetched_at = snapshot.fetched_at
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)
        if now - fetched_at < timedelta(hours=6):
            return ProviderMatchDetails.model_validate(snapshot.payload)

    mapping = await session.scalar(
        select(ExternalIDMapping).where(
            ExternalIDMapping.provider == provider_name,
            ExternalIDMapping.entity_type == CanonicalEntityType.FIXTURE.value,
            ExternalIDMapping.entity_id == fixture_id,
        )
    )
    if mapping is None:
        if snapshot is not None:
            return ProviderMatchDetails.model_validate(snapshot.payload)
        raise HTTPException(status_code=404, detail="Fixture has no provider match identity")
    settings = request.app.state.settings
    token = settings.football_data_api_token
    if not token:
        if snapshot is not None:
            return ProviderMatchDetails.model_validate(snapshot.payload)
        raise HTTPException(status_code=503, detail="Match-report provider is not configured")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            provider = FootballDataOrgProvider(
                token,
                competition_codes=frozenset(settings.football_data_competition_codes),
                client=client,
            )
            report = await provider.fetch_match_details(mapping.external_id)
    except ProviderRateLimitError as exc:
        raise HTTPException(
            status_code=503, detail="Match-report provider rate limit reached"
        ) from exc
    except ProviderConfigurationError as exc:
        raise HTTPException(
            status_code=502, detail="Match-report provider rejected the request"
        ) from exc
    except ProviderUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="Match-report provider is temporarily unavailable"
        ) from exc

    payload = report.model_dump(mode="json")
    if snapshot is None:
        snapshot = FixtureReportSnapshot(
            fixture_id=fixture_id,
            provider=provider_name,
            external_id=mapping.external_id,
            payload=payload,
            fetched_at=now,
        )
        session.add(snapshot)
    else:
        snapshot.external_id = mapping.external_id
        snapshot.payload = payload
        snapshot.fetched_at = now
    await replace_canonical_fixture_report(
        session, provider=provider_name, fixture_id=fixture_id, report=report
    )
    await session.commit()
    return report


async def _validate_competition_season(
    session: AsyncSession, competition_id: str, season_id: str
) -> None:
    competition = await session.get(Competition, competition_id)
    season = await session.get(Season, season_id)
    if competition is None or season is None or season.competition_id != competition_id:
        raise HTTPException(status_code=404, detail="Competition season not found")


@router.get("/competitions/{competition_id}/statistics")
async def competition_statistics(
    competition_id: str,
    session: SessionDep,
    season_id: str,
) -> dict[str, object]:
    """Return scoring and home/away outcome statistics for a competition season."""
    await _validate_competition_season(session, competition_id, season_id)
    statistics = await calculate_competition_statistics(
        session, competition_id=competition_id, season_id=season_id
    )
    return {
        "competition_id": competition_id,
        "season_id": season_id,
        "statistics": statistics,
    }


@router.get("/competitions/{competition_id}/matchdays")
async def competition_matchdays(
    competition_id: str,
    session: SessionDep,
    season_id: str,
) -> dict[str, object]:
    """Summarize each provider-supplied matchday/round without inventing events."""
    await _validate_competition_season(session, competition_id, season_id)
    home = aliased(Team)
    away = aliased(Team)
    result = await session.execute(
        select(Fixture, home.name, away.name)
        .join(home, Fixture.home_team_id == home.id)
        .join(away, Fixture.away_team_id == away.id)
        .where(
            Fixture.competition_id == competition_id,
            Fixture.season_id == season_id,
        )
        .order_by(Fixture.kickoff_at.asc(), Fixture.id.asc())
    )
    rounds: dict[str, list[tuple[Fixture, str, str]]] = {}
    for fixture, home_name, away_name in result.all():
        label = fixture.round_name or f"Unassigned · {fixture.kickoff_at.date().isoformat()}"
        rounds.setdefault(label, []).append((fixture, home_name, away_name))

    summaries: list[dict[str, object]] = []
    for label, fixtures in rounds.items():
        finished = [
            row
            for row in fixtures
            if row[0].status == "finished"
            and row[0].home_score is not None
            and row[0].away_score is not None
        ]

        def scored_goals(row: tuple[Fixture, str, str]) -> int:
            fixture = row[0]
            assert fixture.home_score is not None and fixture.away_score is not None
            return fixture.home_score + fixture.away_score

        goals = sum(scored_goals(row) for row in finished)
        highest = max(
            finished,
            key=lambda row: (scored_goals(row), -row[0].kickoff_at.timestamp()),
            default=None,
        )
        summaries.append(
            {
                "name": label,
                "kickoff_from": fixtures[0][0].kickoff_at,
                "kickoff_to": fixtures[-1][0].kickoff_at,
                "fixtures": len(fixtures),
                "played": len(finished),
                "scheduled": sum(row[0].status == "scheduled" for row in fixtures),
                "live": sum(row[0].status in {"live", "halftime"} for row in fixtures),
                "postponed": sum(row[0].status == "postponed" for row in fixtures),
                "total_goals": goals,
                "average_goals_per_played_match": round(goals / len(finished), 2)
                if finished
                else None,
                "highest_scoring_fixture": (
                    {
                        "fixture_id": highest[0].id,
                        "home_team": highest[1],
                        "away_team": highest[2],
                        "home_score": highest[0].home_score,
                        "away_score": highest[0].away_score,
                        "total_goals": scored_goals(highest),
                    }
                    if highest is not None
                    else None
                ),
            }
        )
    return {
        "competition_id": competition_id,
        "season_id": season_id,
        "total_matchdays": len(summaries),
        "matchdays": summaries,
    }


@router.get("/competitions/{competition_id}/season-comparison")
async def competition_season_comparison(
    competition_id: str, session: SessionDep
) -> dict[str, object]:
    """Compare season scoring and final table leaders for a competition."""
    if await session.get(Competition, competition_id) is None:
        raise HTTPException(status_code=404, detail="Competition not found")
    seasons = await calculate_competition_season_comparison(session, competition_id=competition_id)
    return {"competition_id": competition_id, "seasons": seasons}


@router.get("/competitions/{competition_id}/standings")
async def competition_standings(
    competition_id: str,
    session: SessionDep,
    season_id: str,
) -> dict[str, object]:
    """Return a deterministic 3-1-0 table for one competition season."""
    await _validate_competition_season(session, competition_id, season_id)
    rows = await calculate_standings(session, competition_id=competition_id, season_id=season_id)
    return {
        "competition_id": competition_id,
        "season_id": season_id,
        "scoring": {"win": 3, "draw": 1, "loss": 0},
        "tie_breakers": ["points", "goal_difference", "goals_for", "team_name"],
        "standings": rows,
    }


@router.get("/teams/{team_id}/statistics")
async def team_season_statistics(
    team_id: str, session: SessionDep, competition_id: str, season_id: str
) -> dict[str, object]:
    """Return a team's season totals and home/away performance split."""
    await _validate_competition_season(session, competition_id, season_id)
    if await session.get(Team, team_id) is None:
        raise HTTPException(status_code=404, detail="Team not found")
    statistics = await calculate_team_season_statistics(
        session, competition_id=competition_id, season_id=season_id, team_id=team_id
    )
    return {
        "team_id": team_id,
        "competition_id": competition_id,
        "season_id": season_id,
        "statistics": statistics,
    }


@router.get("/teams/{team_id}/season-comparison")
async def team_season_comparison(
    team_id: str, session: SessionDep, competition_id: str
) -> dict[str, object]:
    """Compare a team's performance and league position across seasons."""
    if await session.get(Competition, competition_id) is None:
        raise HTTPException(status_code=404, detail="Competition not found")
    if await session.get(Team, team_id) is None:
        raise HTTPException(status_code=404, detail="Team not found")
    seasons = await calculate_team_season_comparison(
        session, competition_id=competition_id, team_id=team_id
    )
    return {"team_id": team_id, "competition_id": competition_id, "seasons": seasons}


@router.get("/teams/{team_id}/form")
async def team_form(
    team_id: str,
    session: SessionDep,
    competition_id: str,
    season_id: str,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> dict[str, object]:
    """Return a team's latest completed results in a competition season."""
    await _validate_competition_season(session, competition_id, season_id)
    if await session.get(Team, team_id) is None:
        raise HTTPException(status_code=404, detail="Team not found")
    form = await calculate_team_form(
        session,
        competition_id=competition_id,
        season_id=season_id,
        team_id=team_id,
        limit=limit,
    )
    return {
        "team_id": team_id,
        "competition_id": competition_id,
        "season_id": season_id,
        "form": form,
    }


@router.get("/teams/head-to-head")
async def team_head_to_head(
    session: SessionDep,
    competition_id: str,
    season_id: str,
    team_a_id: str,
    team_b_id: str,
) -> dict[str, object]:
    """Compare completed meetings between two teams in one competition season."""
    await _validate_competition_season(session, competition_id, season_id)
    if team_a_id == team_b_id:
        raise HTTPException(status_code=422, detail="team IDs must be different")
    if await session.get(Team, team_a_id) is None or await session.get(Team, team_b_id) is None:
        raise HTTPException(status_code=404, detail="Team not found")
    summary = await calculate_head_to_head(
        session,
        competition_id=competition_id,
        season_id=season_id,
        team_a_id=team_a_id,
        team_b_id=team_b_id,
    )
    return summary


class FixtureReconciliationCandidate(BaseModel):
    """Read-only evidence that two canonical fixtures may represent one event."""

    model_config = ConfigDict(extra="forbid")

    left_fixture_id: str
    right_fixture_id: str
    competition_id: str
    season_id: str
    home_team_id: str
    away_team_id: str
    left_kickoff_at: datetime
    right_kickoff_at: datetime
    kickoff_difference_seconds: int
    severity: str
    requires_review: bool = True
    reason: str


class FixtureReconciliationPage(BaseModel):
    items: list[FixtureReconciliationCandidate]
    total: int
    limit: int
    offset: int
    read_only: bool = True


class ProviderIdentityMappingRead(BaseModel):
    entity_type: str
    entity_id: str


class ProviderIdentityOverlapRead(BaseModel):
    provider: str
    external_id: str
    mappings: list[ProviderIdentityMappingRead]
    severity: str = "informational"
    requires_review: bool = True
    interpretation: str


class ProviderIdentityOverlapPage(BaseModel):
    items: list[ProviderIdentityOverlapRead]
    total: int
    limit: int
    offset: int
    read_only: bool = True


@router.get(
    "/ops/reconciliation/fixtures",
    response_model=FixtureReconciliationPage,
)
async def preview_fixture_reconciliation(
    session: SessionDep,
    tolerance_minutes: Annotated[int, Query(ge=1, le=180)] = 15,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FixtureReconciliationPage:
    """Preview likely duplicate fixtures; never changes or merges records.

    Candidates require identical competition, season, home/away participants,
    and kick-off times within the requested tolerance. This conservative match
    intentionally misses reversed fixtures and cross-competition reschedules.
    """
    left = aliased(Fixture)
    right = aliased(Fixture)
    tolerance = timedelta(minutes=tolerance_minutes)
    matches = await session.execute(
        select(left, right)
        .where(
            left.id < right.id,
            left.competition_id == right.competition_id,
            left.season_id == right.season_id,
            left.home_team_id == right.home_team_id,
            left.away_team_id == right.away_team_id,
        )
        .order_by(left.kickoff_at, left.id, right.id)
    )
    candidates: list[FixtureReconciliationCandidate] = []
    for first, second in matches.all():
        difference = abs((second.kickoff_at - first.kickoff_at).total_seconds())
        if difference > tolerance.total_seconds():
            continue
        candidates.append(
            FixtureReconciliationCandidate(
                left_fixture_id=first.id,
                right_fixture_id=second.id,
                competition_id=first.competition_id,
                season_id=first.season_id,
                home_team_id=first.home_team_id,
                away_team_id=first.away_team_id,
                left_kickoff_at=first.kickoff_at,
                right_kickoff_at=second.kickoff_at,
                kickoff_difference_seconds=int(difference),
                severity="high" if difference <= 60 else "review",
                reason=(
                    "Same competition, season, home team and away team; kick-off "
                    f"times differ by {int(difference)} seconds. Verify provider "
                    "identities and match history before any manual reconciliation."
                ),
            )
        )
    total = len(candidates)
    return FixtureReconciliationPage(
        items=candidates[offset : offset + limit],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/ops/reconciliation/provider-identities",
    response_model=ProviderIdentityOverlapPage,
)
async def preview_provider_identity_overlaps(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProviderIdentityOverlapPage:
    """List provider IDs reused across canonical entity types for review only.

    The mapping key is intentionally scoped by provider and entity type, so
    the same external ID on (for example) a team and a competition is not
    inherently a conflict. This endpoint surfaces namespace overlaps without
    assuming provider-wide ID uniqueness or changing any mapping.
    """
    grouped = (
        select(ExternalIDMapping.provider, ExternalIDMapping.external_id)
        .group_by(ExternalIDMapping.provider, ExternalIDMapping.external_id)
        .having(func.count(func.distinct(ExternalIDMapping.entity_type)) > 1)
    )
    total = int(await session.scalar(select(func.count()).select_from(grouped.subquery())) or 0)
    identities = (
        await session.execute(
            grouped.order_by(ExternalIDMapping.provider, ExternalIDMapping.external_id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    items: list[ProviderIdentityOverlapRead] = []
    for provider, external_id in identities:
        mappings = (
            await session.scalars(
                select(ExternalIDMapping)
                .where(
                    ExternalIDMapping.provider == provider,
                    ExternalIDMapping.external_id == external_id,
                )
                .order_by(ExternalIDMapping.entity_type, ExternalIDMapping.entity_id)
            )
        ).all()
        items.append(
            ProviderIdentityOverlapRead(
                provider=provider,
                external_id=external_id,
                mappings=[
                    ProviderIdentityMappingRead(
                        entity_type=mapping.entity_type,
                        entity_id=mapping.entity_id,
                    )
                    for mapping in mappings
                ],
                interpretation=(
                    "The provider reuses this external ID across entity types. "
                    "This may be valid type-scoped ID reuse; verify the provider's "
                    "identifier namespace before treating it as a conflict."
                ),
            )
        )
    return ProviderIdentityOverlapPage(items=items, total=total, limit=limit, offset=offset)
