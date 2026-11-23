"""HTTP contract tests for the public sports API."""

import asyncio
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from chezaport.app import create_app
from chezaport.core.config import Settings
from chezaport.core.database import Base
from chezaport.sports.models import (
    Competition,
    Fixture,
    Player,
    Season,
    Sport,
    Team,
    TeamMembership,
)


def test_sports_read_api_and_analytics(tmp_path) -> None:
    database_path = tmp_path / "sports-api.db"
    database_url = f"sqlite+aiosqlite:///{database_path}"

    async def prepare_database() -> tuple[str, str, str, str, str]:
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        from sqlalchemy.ext.asyncio import async_sessionmaker

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            sport = Sport(code="football", name="Association football")
            session.add(sport)
            await session.flush()
            competition = Competition(
                sport_id=sport.id,
                name="Sample League",
                slug="sample-league",
            )
            session.add(competition)
            await session.flush()
            season = Season(competition_id=competition.id, name="2026", is_current=True)
            home = Team(sport_id=sport.id, name="Alpha FC", slug="alpha-fc")
            away = Team(sport_id=sport.id, name="Beta FC", slug="beta-fc")
            player = Player(
                first_name="Ada",
                last_name="Striker",
                display_name="Ada Striker",
                position="Forward",
            )
            session.add_all([season, home, away, player])
            await session.flush()
            session.add(
                TeamMembership(
                    team_id=home.id,
                    player_id=player.id,
                    joined_on=date(2026, 1, 1),
                    shirt_number=9,
                )
            )
            session.add(
                Fixture(
                    competition_id=competition.id,
                    season_id=season.id,
                    home_team_id=home.id,
                    away_team_id=away.id,
                    kickoff_at=datetime(2026, 8, 1, tzinfo=UTC),
                    status="finished",
                    home_score=2,
                    away_score=0,
                )
            )
            await session.commit()
            identifiers = (sport.id, competition.id, season.id, home.id, player.id)
        await engine.dispose()
        return identifiers

    sport_id, competition_id, season_id, team_id, player_id = asyncio.run(prepare_database())
    settings = Settings(database_url=database_url)
    with TestClient(create_app(settings)) as client:
        sports = client.get("/api/v1/sports")
        competitions = client.get("/api/v1/competitions", params={"sport_id": sport_id})
        fixtures = client.get("/api/v1/fixtures", params={"competition_id": competition_id})
        standings = client.get(
            f"/api/v1/competitions/{competition_id}/standings",
            params={"season_id": season_id},
        )
        form = client.get(
            f"/api/v1/teams/{team_id}/form",
            params={"competition_id": competition_id, "season_id": season_id},
        )
        teams = client.get(
            "/api/v1/teams",
            params={"competition_id": competition_id, "season_id": season_id},
        )
        seasons = client.get(
            "/api/v1/seasons",
            params={"competition_id": competition_id, "current_only": True},
        )
        players = client.get(
            "/api/v1/players",
            params={"position": "forward", "search": "Ada"},
        )
        player_detail = client.get(f"/api/v1/players/{player_id}")
        squad = client.get(
            f"/api/v1/teams/{team_id}/squad",
            params={"as_of": "2026-09-01"},
        )
        pre_registration_squad = client.get(
            f"/api/v1/teams/{team_id}/squad",
            params={"as_of": "2025-12-31"},
        )

    assert sports.status_code == 200
    assert sports.json()[0]["code"] == "football"
    assert competitions.status_code == 200
    assert len(competitions.json()) == 1
    assert fixtures.status_code == 200
    assert fixtures.json()["total"] == 1
    assert fixtures.json()["items"][0]["home_team_name"] == "Alpha FC"
    assert standings.status_code == 200
    assert standings.json()["standings"][0]["points"] == 3
    assert form.status_code == 200
    assert form.json()["form"][0]["outcome"] == "W"
    assert teams.status_code == 200
    assert teams.json()["total"] == 2
    assert teams.json()["items"][0]["name"] == "Alpha FC"
    assert seasons.status_code == 200
    assert seasons.json()["total"] == 1
    assert seasons.json()["items"][0]["is_current"] is True
    assert players.status_code == 200
    assert players.json()["total"] == 1
    assert players.json()["items"][0]["display_name"] == "Ada Striker"
    assert player_detail.status_code == 200
    assert player_detail.json()["memberships"][0]["team_name"] == "Alpha FC"
    assert squad.status_code == 200
    assert squad.json()["items"][0]["shirt_number"] == 9
    assert pre_registration_squad.status_code == 200
    assert pre_registration_squad.json()["total"] == 0
