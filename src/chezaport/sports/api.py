"""Read-only, versioned sports API for catalog, fixtures, and analytics."""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from chezaport.sports.models import (
    Competition,
    Country,
    Fixture,
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
    season_mismatch = int(
        await session.scalar(
            select(func.count())
            .select_from(Fixture)
            .join(Season, Fixture.season_id == Season.id)
            .where(Fixture.competition_id != Season.competition_id)
        )
        or 0
    )
    checks = [
        {"code": "finished_fixture_missing_score", "count": finished_missing_score},
        {"code": "fixture_partial_score", "count": partial_score},
        {"code": "fixture_season_competition_mismatch", "count": season_mismatch},
    ]
    total_issues = finished_missing_score + partial_score + season_mismatch
    return {
        "status": "healthy" if total_issues == 0 else "degraded",
        "total_issues": total_issues,
        "checks": checks,
        "generated_at": datetime.now(UTC),
        "scope": "canonical database integrity checks; not source verification",
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
    rows = await session.scalars(
        select(SportsSyncRun).order_by(SportsSyncRun.started_at.desc(), SportsSyncRun.id.desc())
    )
    latest: dict[tuple[str, str], SportsSyncRun] = {}
    for run in rows.all():
        latest.setdefault((run.provider, run.resource), run)
    now = datetime.now(UTC)
    result: list[SyncFreshnessRead] = []
    for (provider, resource), run in sorted(latest.items()):
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
