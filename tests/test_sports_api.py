"""HTTP contract tests for the public sports API."""

import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from chezaport.app import create_app
from chezaport.core.config import Settings
from chezaport.core.database import Base
from chezaport.sports.models import Competition, Fixture, Season, Sport, Team


def test_sports_read_api_and_analytics(tmp_path) -> None:
    database_path = tmp_path / "sports-api.db"
    database_url = f"sqlite+aiosqlite:///{database_path}"

    async def prepare_database() -> tuple[str, str, str, str]:
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
            season = Season(competition_id=competition.id, name="2026")
            home = Team(sport_id=sport.id, name="Alpha FC", slug="alpha-fc")
            away = Team(sport_id=sport.id, name="Beta FC", slug="beta-fc")
            session.add_all([season, home, away])
            await session.flush()
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
            identifiers = (sport.id, competition.id, season.id, home.id)
        await engine.dispose()
        return identifiers

    sport_id, competition_id, season_id, team_id = asyncio.run(prepare_database())
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
