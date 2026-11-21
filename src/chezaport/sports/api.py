"""Read-only, versioned sports API for catalog, fixtures, and analytics."""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from chezaport.sports.models import Competition, Fixture, Season, Sport, Team
from chezaport.sports.services.analytics import (
    calculate_head_to_head,
    calculate_standings,
    calculate_team_form,
)

router = APIRouter(tags=["sports"])


async def _session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.db_session_factory
    async with factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(_session)]


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


async def _validate_competition_season(
    session: AsyncSession, competition_id: str, season_id: str
) -> None:
    competition = await session.get(Competition, competition_id)
    season = await session.get(Season, season_id)
    if competition is None or season is None or season.competition_id != competition_id:
        raise HTTPException(status_code=404, detail="Competition season not found")


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
