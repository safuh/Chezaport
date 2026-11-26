"""Contract tests for provider-backed player statistics."""

import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from chezaport.app import create_app
from chezaport.core.config import Settings
from chezaport.core.database import Base
from chezaport.sports.models import (
    Competition,
    ExternalIDMapping,
    Fixture,
    FixtureReportSnapshot,
    Player,
    Season,
    Sport,
    Team,
)


def test_player_statistics_aggregate_report_events_without_counting_bench_only(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'player-statistics.db'}"

    async def prepare_database() -> tuple[str, str, str, str]:
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            sport = Sport(code="football", name="Association football")
            session.add(sport)
            await session.flush()
            competition = Competition(sport_id=sport.id, name="Test League", slug="test-league")
            session.add(competition)
            await session.flush()
            season = Season(competition_id=competition.id, name="2026")
            home = Team(sport_id=sport.id, name="Home FC", slug="home-fc")
            away = Team(sport_id=sport.id, name="Away FC", slug="away-fc")
            player = Player(display_name="Alex Forward", position="Forward")
            bench_only = Player(display_name="Bench Only", position="Midfielder")
            unlinked = Player(display_name="Unlinked Player", position="Defender")
            session.add_all([season, home, away, player, bench_only, unlinked])
            await session.flush()
            fixtures = [
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
                    home_team_id=home.id,
                    away_team_id=away.id,
                    kickoff_at=datetime(2026, 8, 8, tzinfo=UTC),
                    status="finished",
                    home_score=0,
                    away_score=0,
                ),
            ]
            session.add_all(fixtures)
            await session.flush()
            session.add_all(
                [
                    ExternalIDMapping(
                        provider="football-data-org",
                        entity_type="player",
                        entity_id=player.id,
                        external_id="player-10",
                    ),
                    ExternalIDMapping(
                        provider="football-data-org",
                        entity_type="player",
                        entity_id=bench_only.id,
                        external_id="player-20",
                    ),
                ]
            )
            base_report = {
                "external_id": "fixture-1",
                "kickoff_at": "2026-08-01T00:00:00Z",
                "status": "finished",
                "home_team": {
                    "external_id": "home",
                    "lineup": [{"external_id": "player-10", "name": "Alex Forward"}],
                    "bench": [{"external_id": "player-20", "name": "Bench Only"}],
                },
                "away_team": {"external_id": "away"},
                "goals": [
                    {
                        "minute": 30,
                        "scorer_external_id": "player-10",
                        "assist_external_id": "player-20",
                    },
                    {"minute": 30, "scorer_external_id": "player-10"},
                ],
                "bookings": [
                    {"minute": 45, "player_external_id": "player-10", "card": "yellow"},
                    {"minute": 45, "player_external_id": "player-10", "card": "red"},
                ],
                "substitutions": [
                    {
                        "minute": 80,
                        "player_out_external_id": "player-10",
                        "player_in_external_id": "player-20",
                    }
                ],
            }
            bench_report = {
                "external_id": "fixture-2",
                "kickoff_at": "2026-08-08T00:00:00Z",
                "status": "finished",
                "home_team": {
                    "external_id": "home",
                    "bench": [{"external_id": "player-10", "name": "Alex Forward"}],
                },
                "away_team": {"external_id": "away"},
            }
            session.add_all(
                [
                    FixtureReportSnapshot(
                        fixture_id=fixtures[0].id,
                        provider="football-data-org",
                        external_id="fixture-1",
                        payload=base_report,
                        fetched_at=datetime(2026, 8, 2, tzinfo=UTC),
                    ),
                    FixtureReportSnapshot(
                        fixture_id=fixtures[1].id,
                        provider="football-data-org",
                        external_id="fixture-2",
                        payload=bench_report,
                        fetched_at=datetime(2026, 8, 9, tzinfo=UTC),
                    ),
                ]
            )
            await session.commit()
            result = (player.id, bench_only.id, unlinked.id, competition.id, season.id)
        await engine.dispose()
        return result

    player_id, bench_only_id, unlinked_player_id, competition_id, season_id = asyncio.run(
        prepare_database()
    )
    with TestClient(create_app(Settings(database_url=database_url))) as client:
        response = client.get(
            f"/api/v1/players/{player_id}/statistics",
            params={"competition_id": competition_id, "season_id": season_id},
        )
        history = client.get(
            f"/api/v1/players/{player_id}/matches",
            params={"competition_id": competition_id, "season_id": season_id},
        )
        history_page = client.get(
            f"/api/v1/players/{player_id}/matches",
            params={"competition_id": competition_id, "season_id": season_id, "limit": 1},
        )
        substitute_stats = client.get(f"/api/v1/players/{bench_only_id}/statistics")
        no_identity = client.get(f"/api/v1/players/{unlinked_player_id}/statistics")
        unlinked_history = client.get(f"/api/v1/players/{unlinked_player_id}/matches")
        leaderboard = client.get(
            f"/api/v1/competitions/{competition_id}/player-leaderboard",
            params={"season_id": season_id, "metric": "goals"},
        )
        assist_leaderboard = client.get(
            f"/api/v1/competitions/{competition_id}/player-leaderboard",
            params={"season_id": season_id, "metric": "assists"},
        )
        invalid_leaderboard = client.get(
            f"/api/v1/competitions/{competition_id}/player-leaderboard",
            params={"season_id": season_id, "metric": "minutes"},
        )
        missing = client.get("/api/v1/players/not-a-player/statistics")

    assert response.status_code == 200
    stats = response.json()
    assert stats["provider_identity_linked"] is True
    assert stats["fixtures_with_reports"] == 2
    assert stats["appearances"] == 1
    assert stats["starts"] == 1
    assert stats["goals"] == 2  # Same-minute goals are distinct provider events.
    assert stats["assists"] == 0
    assert stats["yellow_cards"] == 1
    assert stats["red_cards"] == 1
    assert stats["substitutions_out"] == 1
    assert stats["minutes_played"] is None
    assert history.status_code == 200
    history_data = history.json()
    assert history_data["provider_identity_linked"] is True
    assert history_data["total"] == 1
    assert len(history_data["items"]) == 1
    match = history_data["items"][0]
    assert match["appeared"] is True
    assert match["started"] is True
    assert match["goals"] == 2
    assert match["yellow_cards"] == 1
    assert match["red_cards"] == 1
    assert match["minutes_played"] is None
    assert history_page.json()["total"] == 1
    assert len(history_page.json()["items"]) == 1
    assert unlinked_history.status_code == 200
    assert unlinked_history.json()["provider_identity_linked"] is False
    assert unlinked_history.json()["items"] == []
    assert leaderboard.status_code == 200
    leaderboard_data = leaderboard.json()
    assert leaderboard_data["metric"] == "goals"
    assert leaderboard_data["items"][0]["player_id"] == player_id
    assert leaderboard_data["items"][0]["goals"] == 2
    assert leaderboard_data["items"][0]["rank"] == 1
    assert assist_leaderboard.status_code == 200
    assert assist_leaderboard.json()["items"][0]["player_id"] == bench_only_id
    assert invalid_leaderboard.status_code == 422
    assert substitute_stats.status_code == 200
    assert substitute_stats.json()["assists"] == 1
    assert substitute_stats.json()["substitutions_in"] == 1
    assert substitute_stats.json()["appearances"] == 1
    assert substitute_stats.json()["starts"] == 0
    assert no_identity.status_code == 200
    assert no_identity.json()["provider_identity_linked"] is False
    assert no_identity.json()["appearances"] == 0
    assert missing.status_code == 404
