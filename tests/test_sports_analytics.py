"""Deterministic regression tests for standings, form, and head-to-head analytics."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from chezaport.core.database import Base
from chezaport.sports.models import Competition, Fixture, Season, Sport, Team
from chezaport.sports.services.analytics import (
    calculate_head_to_head,
    calculate_standings,
    calculate_team_form,
)


@pytest.fixture
async def analytics_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            sport = Sport(code="football", name="Association football")
            session.add(sport)
            await session.flush()
            competition = Competition(
                sport_id=sport.id,
                name="Sample League",
                slug="sample-league",
                competition_type="league",
            )
            session.add(competition)
            await session.flush()
            season = Season(competition_id=competition.id, name="2026")
            home = Team(sport_id=sport.id, name="Alpha FC", slug="alpha-fc")
            away = Team(sport_id=sport.id, name="Beta FC", slug="beta-fc")
            third = Team(sport_id=sport.id, name="Gamma FC", slug="gamma-fc")
            session.add_all([season, home, away, third])
            await session.flush()
            session.add_all(
                [
                    Fixture(
                        competition_id=competition.id,
                        season_id=season.id,
                        home_team_id=home.id,
                        away_team_id=away.id,
                        kickoff_at=datetime(2026, 8, 1, tzinfo=UTC),
                        status="finished",
                        home_score=2,
                        away_score=0,
                    ),
                    Fixture(
                        competition_id=competition.id,
                        season_id=season.id,
                        home_team_id=away.id,
                        away_team_id=home.id,
                        kickoff_at=datetime(2026, 8, 8, tzinfo=UTC),
                        status="finished",
                        home_score=1,
                        away_score=1,
                    ),
                    Fixture(
                        competition_id=competition.id,
                        season_id=season.id,
                        home_team_id=home.id,
                        away_team_id=third.id,
                        kickoff_at=datetime(2026, 8, 15, tzinfo=UTC),
                        status="scheduled",
                    ),
                ]
            )
            await session.flush()
            yield session, competition.id, season.id, home.id, away.id, third.id
    finally:
        await engine.dispose()


async def test_standings_ignore_unfinished_fixtures_and_apply_three_one_zero(analytics_session):
    session, competition_id, season_id, home_id, away_id, third_id = analytics_session

    table = await calculate_standings(session, competition_id=competition_id, season_id=season_id)

    assert [row["team_id"] for row in table] == [home_id, away_id]
    assert table[0]["played"] == 2
    assert table[0]["won"] == 1
    assert table[0]["drawn"] == 1
    assert table[0]["points"] == 4
    assert table[0]["goal_difference"] == 2
    assert table[0]["form"] == "WD"
    assert table[1]["points"] == 1
    assert third_id not in {row["team_id"] for row in table}


async def test_team_form_is_newest_first_and_limited(analytics_session):
    session, competition_id, season_id, home_id, _, _ = analytics_session

    form = await calculate_team_form(
        session,
        competition_id=competition_id,
        season_id=season_id,
        team_id=home_id,
        limit=1,
    )

    assert len(form) == 1
    assert form[0]["outcome"] == "D"
    assert form[0]["venue"] == "away"
    assert form[0]["goals_for"] == 1


async def test_head_to_head_aggregates_both_venues(analytics_session):
    session, competition_id, season_id, home_id, away_id, _ = analytics_session

    summary = await calculate_head_to_head(
        session,
        competition_id=competition_id,
        season_id=season_id,
        team_a_id=home_id,
        team_b_id=away_id,
    )

    assert summary["played"] == 2
    assert summary["team_a_wins"] == 1
    assert summary["draws"] == 1
    assert summary["team_b_wins"] == 0
    assert summary["team_a_goals"] == 3
    assert summary["team_b_goals"] == 1
    assert len(summary["meetings"]) == 2


async def test_head_to_head_rejects_same_team(analytics_session):
    session, competition_id, season_id, home_id, _, _ = analytics_session

    with pytest.raises(ValueError, match="different"):
        await calculate_head_to_head(
            session,
            competition_id=competition_id,
            season_id=season_id,
            team_a_id=home_id,
            team_b_id=home_id,
        )
