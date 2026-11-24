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
    Country,
    ExternalIDMapping,
    Fixture,
    Player,
    Season,
    Sport,
    SportsSyncRun,
    Team,
    TeamMembership,
    Venue,
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
            country = Country(code="GBR", name="United Kingdom")
            session.add(country)
            await session.flush()
            venue = Venue(
                name="Alpha Ground",
                city="London",
                country_id=country.id,
                capacity=60000,
            )
            session.add(venue)
            await session.flush()
            home = Team(
                sport_id=sport.id,
                country_id=country.id,
                venue_id=venue.id,
                name="Alpha FC",
                slug="alpha-fc",
            )
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
                    round_name="Matchday 1",
                )
            )
            session.add(
                Fixture(
                    competition_id=competition.id,
                    season_id=season.id,
                    home_team_id=home.id,
                    away_team_id=away.id,
                    kickoff_at=datetime(2026, 8, 8, tzinfo=UTC),
                    status="finished",
                    home_score=None,
                    away_score=None,
                    round_name="Integrity test anomaly",
                )
            )
            session.add(
                ExternalIDMapping(
                    provider="sample-provider",
                    entity_type="player",
                    entity_id="missing-canonical-player",
                    external_id="provider-player-404",
                )
            )
            session.add(
                SportsSyncRun(
                    provider="demo-provider",
                    resource="fixtures",
                    status="succeeded",
                    started_at=datetime(2026, 8, 1, tzinfo=UTC),
                    completed_at=datetime(2026, 8, 1, 0, 0, 5, tzinfo=UTC),
                    records_fetched=1,
                    records_seen=1,
                    created=1,
                )
            )
            await session.commit()
            identifiers = (sport.id, competition.id, season.id, home.id, player.id)
        await engine.dispose()
        return identifiers

    sport_id, competition_id, season_id, team_id, player_id = asyncio.run(prepare_database())
    settings = Settings(database_url=database_url)
    app = create_app(settings)

    with TestClient(app) as client:
        sync_runs = client.get("/api/v1/ops/sync-runs")
        freshness = client.get("/api/v1/ops/sync-freshness")
        data_quality = client.get("/api/v1/ops/data-quality")
        dashboard = client.get("/")
        sports = client.get("/api/v1/sports")
        competitions = client.get("/api/v1/competitions", params={"sport_id": sport_id})
        fixtures = client.get("/api/v1/fixtures", params={"competition_id": competition_id})
        fixture_detail = client.get(f"/api/v1/fixtures/{fixtures.json()['items'][0]['id']}")
        missing_fixture = client.get("/api/v1/fixtures/not-a-real-fixture")
        statistics = client.get(
            f"/api/v1/competitions/{competition_id}/statistics",
            params={"season_id": season_id},
        )
        season_comparison = client.get(f"/api/v1/competitions/{competition_id}/season-comparison")
        matchdays = client.get(
            f"/api/v1/competitions/{competition_id}/matchdays",
            params={"season_id": season_id},
        )
        team_season_comparison = client.get(
            f"/api/v1/teams/{team_id}/season-comparison",
            params={"competition_id": competition_id},
        )
        standings = client.get(
            f"/api/v1/competitions/{competition_id}/standings",
            params={"season_id": season_id},
        )
        form = client.get(
            f"/api/v1/teams/{team_id}/form",
            params={"competition_id": competition_id, "season_id": season_id},
        )
        team_statistics = client.get(
            f"/api/v1/teams/{team_id}/statistics",
            params={"competition_id": competition_id, "season_id": season_id},
        )
        countries = client.get("/api/v1/countries", params={"search": "United"})
        venues = client.get("/api/v1/venues", params={"search": "Alpha Ground"})
        teams = client.get(
            "/api/v1/teams",
            params={"competition_id": competition_id, "season_id": season_id},
        )
        team_detail = client.get(f"/api/v1/teams/{team_id}")
        missing_team = client.get("/api/v1/teams/not-a-real-team")
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

    assert sync_runs.status_code == 200
    assert sync_runs.json()["total"] == 1
    assert sync_runs.json()["items"][0]["duration_seconds"] == 5.0
    assert freshness.status_code == 200
    assert freshness.json()[0]["provider"] == "demo-provider"
    assert freshness.json()[0]["is_stale"] is True
    assert data_quality.status_code == 200
    assert data_quality.json()["status"] == "degraded"
    assert data_quality.json()["total_issues"] == 2
    quality_checks = {item["code"]: item["count"] for item in data_quality.json()["checks"]}
    assert quality_checks["finished_fixture_missing_score"] == 1
    assert quality_checks["orphan_external_id_mapping"] == 1
    assert "Provider mappings with missing canonical records" in dashboard.text
    assert dashboard.status_code == 200
    assert "League table" in dashboard.text
    assert "Team intelligence" in dashboard.text
    assert "/ops/sync-freshness" in dashboard.text
    assert "display refresh 30s" in dashboard.text
    assert "Football-Data.org API" in dashboard.text
    assert "Match centre" in dashboard.text
    assert "/matchdays" in dashboard.text
    assert "Matchday summaries" in dashboard.text
    assert "loadFixture" in dashboard.text
    assert "getAllFixtures" in dashboard.text
    assert "Latest " in dashboard.text
    assert sports.status_code == 200
    assert sports.json()[0]["code"] == "football"
    assert competitions.status_code == 200
    assert len(competitions.json()) == 1
    assert fixtures.status_code == 200
    assert fixtures.json()["total"] == 2
    assert fixtures.json()["items"][0]["home_team_name"] == "Alpha FC"
    assert fixture_detail.status_code == 200
    assert fixture_detail.json()["competition_name"] == "Sample League"
    assert fixture_detail.json()["season_name"] == "2026"
    assert fixture_detail.json()["venue_name"] is None
    assert missing_fixture.status_code == 404
    assert statistics.status_code == 200
    assert statistics.json()["statistics"]["played"] == 1
    assert statistics.json()["statistics"]["total_goals"] == 2
    assert statistics.json()["statistics"]["average_goals_per_match"] == 2.0
    assert statistics.json()["statistics"]["home_wins"] == 1
    assert season_comparison.status_code == 200
    assert matchdays.status_code == 200
    assert matchdays.json()["total_matchdays"] == 2
    assert matchdays.json()["matchdays"][0]["name"] == "Matchday 1"
    assert matchdays.json()["matchdays"][0]["total_goals"] == 2
    assert matchdays.json()["matchdays"][0]["highest_scoring_fixture"]["home_team"] == "Alpha FC"
    assert len(season_comparison.json()["seasons"]) == 1
    assert season_comparison.json()["seasons"][0]["leader"]["team_name"] == "Alpha FC"
    assert team_season_comparison.status_code == 200
    assert len(team_season_comparison.json()["seasons"]) == 1
    assert team_season_comparison.json()["seasons"][0]["position"] == 1
    assert team_season_comparison.json()["seasons"][0]["statistics"]["played"] == 1
    assert standings.status_code == 200
    assert standings.json()["standings"][0]["points"] == 3
    assert form.status_code == 200
    assert form.json()["form"][0]["outcome"] == "W"
    assert team_statistics.status_code == 200
    assert team_statistics.json()["statistics"]["played"] == 1
    assert team_statistics.json()["statistics"]["won"] == 1
    assert team_statistics.json()["statistics"]["goals_for"] == 2
    assert team_statistics.json()["statistics"]["clean_sheets"] == 1
    assert team_statistics.json()["statistics"]["home"]["win_rate"] == 100.0
    assert countries.status_code == 200
    assert countries.json()["total"] == 1
    assert countries.json()["items"][0]["code"] == "GBR"
    assert venues.status_code == 200
    assert venues.json()["total"] == 1
    assert venues.json()["items"][0]["capacity"] == 60000
    assert teams.status_code == 200
    assert teams.json()["total"] == 2
    assert teams.json()["items"][0]["name"] == "Alpha FC"
    assert team_detail.status_code == 200
    assert team_detail.json()["country_name"] == "United Kingdom"
    assert team_detail.json()["venue_name"] == "Alpha Ground"
    assert team_detail.json()["venue_capacity"] == 60000
    assert missing_team.status_code == 404
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


def test_data_quality_detects_fixture_participant_sport_mismatch(tmp_path) -> None:
    database_path = tmp_path / "sports-quality.db"
    database_url = f"sqlite+aiosqlite:///{database_path}"

    async def prepare_database() -> None:
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        from sqlalchemy.ext.asyncio import async_sessionmaker

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            football = Sport(code="football", name="Association football")
            basketball = Sport(code="basketball", name="Basketball")
            session.add_all([football, basketball])
            await session.flush()
            competition = Competition(
                sport_id=football.id, name="Sample League", slug="sample-league"
            )
            session.add(competition)
            await session.flush()
            season = Season(competition_id=competition.id, name="2026")
            home = Team(sport_id=football.id, name="Home FC", slug="home-fc")
            away = Team(sport_id=basketball.id, name="Away BC", slug="away-bc")
            session.add_all([competition, season, home, away])
            await session.flush()
            session.add(
                Fixture(
                    competition_id=competition.id,
                    season_id=season.id,
                    home_team_id=home.id,
                    away_team_id=away.id,
                    kickoff_at=datetime(2026, 8, 1, tzinfo=UTC),
                )
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(prepare_database())
    app = create_app(Settings(database_url=database_url))
    with TestClient(app) as client:
        response = client.get("/api/v1/ops/data-quality")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    checks = {item["code"]: item["count"] for item in payload["checks"]}
    assert checks["fixture_participant_sport_mismatch"] == 1
    assert payload["total_issues"] == 1
