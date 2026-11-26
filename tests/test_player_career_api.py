"""Contract tests for historical player career and team contributions."""

import asyncio
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from chezaport.app import create_app
from chezaport.core.config import Settings
from chezaport.core.database import Base
from chezaport.sports.models import (
    Competition,
    ExternalIDMapping,
    Fixture,
    FixtureMatchEvent,
    FixturePlayerParticipation,
    Player,
    Season,
    Sport,
    Team,
    TeamMembership,
)


def test_player_career_and_team_contributions_respect_transfer_history(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'player-career.db'}"

    async def prepare_database() -> dict[str, str]:
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            sport = Sport(code="football", name="Association football")
            session.add(sport)
            await session.flush()

            league = Competition(sport_id=sport.id, name="Test League", slug="test-league")
            cup = Competition(sport_id=sport.id, name="Test Cup", slug="test-cup")
            session.add_all([league, cup])
            await session.flush()

            league_season = Season(competition_id=league.id, name="2025/26")
            cup_season = Season(competition_id=cup.id, name="2025/26")
            alpha = Team(sport_id=sport.id, name="Alpha FC", slug="alpha-fc")
            beta = Team(sport_id=sport.id, name="Beta FC", slug="beta-fc")
            gamma = Team(sport_id=sport.id, name="Gamma FC", slug="gamma-fc")
            alex = Player(display_name="Alex Forward", position="Forward")
            ben = Player(display_name="Ben Midfielder", position="Midfielder")
            historical_only = Player(display_name="Historical Player", position="Defender")
            session.add_all(
                [
                    league_season,
                    cup_season,
                    alpha,
                    beta,
                    gamma,
                    alex,
                    ben,
                    historical_only,
                ]
            )
            await session.flush()

            fixtures = [
                Fixture(
                    competition_id=league.id,
                    season_id=league_season.id,
                    home_team_id=alpha.id,
                    away_team_id=gamma.id,
                    kickoff_at=datetime(2025, 8, 1, tzinfo=UTC),
                    status="finished",
                    home_score=1,
                    away_score=0,
                ),
                Fixture(
                    competition_id=league.id,
                    season_id=league_season.id,
                    home_team_id=beta.id,
                    away_team_id=gamma.id,
                    kickoff_at=datetime(2025, 8, 8, tzinfo=UTC),
                    status="finished",
                    home_score=1,
                    away_score=0,
                ),
                Fixture(
                    competition_id=cup.id,
                    season_id=cup_season.id,
                    home_team_id=beta.id,
                    away_team_id=alpha.id,
                    kickoff_at=datetime(2025, 8, 15, tzinfo=UTC),
                    status="finished",
                    home_score=2,
                    away_score=0,
                ),
            ]
            session.add_all(fixtures)
            await session.flush()

            session.add_all(
                [
                    TeamMembership(
                        team_id=alpha.id,
                        player_id=alex.id,
                        joined_on=date(2025, 7, 1),
                        left_on=date(2025, 8, 4),
                        shirt_number=9,
                    ),
                    TeamMembership(
                        team_id=beta.id,
                        player_id=alex.id,
                        joined_on=date(2025, 8, 5),
                        left_on=None,
                        shirt_number=10,
                    ),
                    TeamMembership(
                        team_id=alpha.id,
                        player_id=ben.id,
                        joined_on=date(2025, 7, 1),
                        left_on=None,
                        shirt_number=8,
                    ),
                    TeamMembership(
                        team_id=alpha.id,
                        player_id=historical_only.id,
                        joined_on=date(2024, 7, 1),
                        left_on=date(2025, 6, 30),
                        shirt_number=4,
                    ),
                ]
            )
            session.add_all(
                [
                    ExternalIDMapping(
                        provider="football-data-org",
                        entity_type="team",
                        entity_id=alpha.id,
                        external_id="team-alpha",
                    ),
                    ExternalIDMapping(
                        provider="football-data-org",
                        entity_type="team",
                        entity_id=beta.id,
                        external_id="team-beta",
                    ),
                    ExternalIDMapping(
                        provider="football-data-org",
                        entity_type="team",
                        entity_id=gamma.id,
                        external_id="team-gamma",
                    ),
                    ExternalIDMapping(
                        provider="football-data-org",
                        entity_type="player",
                        entity_id=alex.id,
                        external_id="player-alex",
                    ),
                    ExternalIDMapping(
                        provider="football-data-org",
                        entity_type="player",
                        entity_id=ben.id,
                        external_id="player-ben",
                    ),
                ]
            )
            await session.flush()

            participations = [
                FixturePlayerParticipation(
                    provider="football-data-org",
                    fixture_id=fixtures[0].id,
                    player_external_id="player-alex",
                    player_name="Alex Forward",
                    team_external_id="team-alpha",
                    is_starter=True,
                    appeared=True,
                ),
                FixturePlayerParticipation(
                    provider="football-data-org",
                    fixture_id=fixtures[0].id,
                    player_external_id="player-ben",
                    player_name="Ben Midfielder",
                    team_external_id=None,
                    is_bench=True,
                    appeared=True,
                ),
                FixturePlayerParticipation(
                    provider="football-data-org",
                    fixture_id=fixtures[1].id,
                    player_external_id="player-alex",
                    player_name="Alex Forward",
                    team_external_id="team-beta",
                    is_bench=True,
                    appeared=True,
                ),
                FixturePlayerParticipation(
                    provider="football-data-org",
                    fixture_id=fixtures[1].id,
                    player_external_id="player-unlinked",
                    player_name="Unlinked Provider Player",
                    team_external_id="team-beta",
                    is_starter=True,
                    appeared=True,
                ),
                FixturePlayerParticipation(
                    provider="football-data-org",
                    fixture_id=fixtures[2].id,
                    player_external_id="player-alex",
                    player_name="Alex Forward",
                    team_external_id="team-beta",
                    is_starter=True,
                    appeared=True,
                ),
            ]
            session.add_all(participations)

            events = [
                FixtureMatchEvent(
                    provider="football-data-org",
                    fixture_id=fixtures[0].id,
                    event_type="goal",
                    source_key="goal-alpha-1",
                    minute=30,
                    player_external_id="player-alex",
                    secondary_player_external_id="player-ben",
                    payload={"team_external_id": "team-alpha"},
                ),
                FixtureMatchEvent(
                    provider="football-data-org",
                    fixture_id=fixtures[0].id,
                    event_type="booking",
                    source_key="booking-alpha-1",
                    minute=45,
                    player_external_id="player-alex",
                    payload={"team_external_id": "team-alpha", "card": "yellow"},
                ),
                FixtureMatchEvent(
                    provider="football-data-org",
                    fixture_id=fixtures[0].id,
                    event_type="substitution",
                    source_key="sub-alpha-1",
                    minute=80,
                    player_external_id="player-ben",
                    secondary_player_external_id="player-alex",
                    payload={"team_external_id": "team-alpha"},
                ),
                FixtureMatchEvent(
                    provider="football-data-org",
                    fixture_id=fixtures[1].id,
                    event_type="goal",
                    source_key="goal-beta-1",
                    minute=25,
                    player_external_id="player-alex",
                    payload={"team_external_id": "team-beta"},
                ),
                FixtureMatchEvent(
                    provider="football-data-org",
                    fixture_id=fixtures[1].id,
                    event_type="booking",
                    source_key="booking-beta-1",
                    minute=60,
                    player_external_id="player-alex",
                    payload={"team_external_id": "team-beta", "card": "red"},
                ),
                FixtureMatchEvent(
                    provider="football-data-org",
                    fixture_id=fixtures[2].id,
                    event_type="goal",
                    source_key="goal-beta-2",
                    minute=15,
                    player_external_id="player-alex",
                    payload={"team_external_id": "team-beta"},
                ),
                FixtureMatchEvent(
                    provider="football-data-org",
                    fixture_id=fixtures[2].id,
                    event_type="goal",
                    source_key="goal-beta-3",
                    minute=70,
                    player_external_id="player-alex",
                    payload={"team_external_id": "team-beta"},
                ),
            ]
            session.add_all(events)
            await session.commit()
            result = {
                "player_id": alex.id,
                "ben_id": ben.id,
                "historical_only_id": historical_only.id,
                "alpha_id": alpha.id,
                "beta_id": beta.id,
                "league_id": league.id,
                "league_season_id": league_season.id,
                "cup_id": cup.id,
                "cup_season_id": cup_season.id,
            }
        await engine.dispose()
        return result

    ids = asyncio.run(prepare_database())
    with TestClient(create_app(Settings(database_url=database_url))) as client:
        career = client.get(f"/api/v1/players/{ids['player_id']}/career")
        alpha = client.get(
            f"/api/v1/teams/{ids['alpha_id']}/player-contributions",
            params={"metric": "assists"},
        )
        beta = client.get(f"/api/v1/teams/{ids['beta_id']}/player-contributions")
        beta_cup = client.get(
            f"/api/v1/teams/{ids['beta_id']}/player-contributions",
            params={
                "competition_id": ids["cup_id"],
                "season_id": ids["cup_season_id"],
            },
        )
        unlinked_career = client.get(f"/api/v1/players/{ids['historical_only_id']}/career")
        missing_player = client.get("/api/v1/players/missing/career")
        missing_team = client.get("/api/v1/teams/missing/player-contributions")

    assert career.status_code == 200
    career_data = career.json()
    assert career_data["provider_identity_linked"] is True
    assert career_data["totals"]["appearances"] == 3
    assert career_data["totals"]["starts"] == 2
    assert career_data["totals"]["goals"] == 4
    assert career_data["totals"]["yellow_cards"] == 1
    assert career_data["totals"]["red_cards"] == 1
    assert career_data["totals"]["substitutions_out"] == 1
    assert [club["team_name"] for club in career_data["clubs"]] == ["Alpha FC", "Beta FC"]
    alpha_career, beta_career = career_data["clubs"]
    assert alpha_career["appearances"] == 1
    assert alpha_career["goals"] == 1
    assert beta_career["appearances"] == 2
    assert beta_career["goals"] == 3
    assert beta_career["red_cards"] == 1
    assert len(beta_career["competitions"]) == 2
    assert career_data["coverage"]["outside_membership_participations"] == 0

    assert alpha.status_code == 200
    alpha_data = alpha.json()
    assert alpha_data["metric"] == "assists"
    assert alpha_data["membership_players"] == 3
    assert alpha_data["linked_players"] == 2
    assert alpha_data["unattributed_provider_participations"] == 0
    assert alpha_data["items"][0]["player_id"] == ids["ben_id"]
    assert alpha_data["items"][0]["assists"] == 1
    assert any(item["player_id"] == ids["historical_only_id"] for item in alpha_data["items"])

    assert beta.status_code == 200
    beta_data = beta.json()
    alex_beta = beta_data["items"][0]
    assert alex_beta["player_id"] == ids["player_id"]
    assert alex_beta["appearances"] == 2
    assert alex_beta["goals"] == 3
    assert alex_beta["red_cards"] == 1
    assert beta_data["unlinked_provider_players"] == 1

    assert beta_cup.status_code == 200
    beta_cup_data = beta_cup.json()
    assert beta_cup_data["total"] == 1
    assert beta_cup_data["items"][0]["appearances"] == 1
    assert beta_cup_data["items"][0]["goals"] == 2

    assert unlinked_career.status_code == 200
    assert unlinked_career.json()["provider_identity_linked"] is False
    assert unlinked_career.json()["clubs"][0]["team_name"] == "Alpha FC"
    assert unlinked_career.json()["totals"]["appearances"] == 0
    assert missing_player.status_code == 404
    assert missing_team.status_code == 404
