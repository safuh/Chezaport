"""Tests for idempotent canonical match-report persistence."""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from chezaport.core.database import Base
from chezaport.sports.integrations.schemas import ProviderMatchDetails
from chezaport.sports.models import (
    Competition,
    Fixture,
    FixtureMatchEvent,
    FixturePlayerParticipation,
    Season,
    Sport,
    Team,
)
from chezaport.sports.services.match_report_persistence import replace_canonical_fixture_report


def test_report_import_is_idempotent_and_replaces_corrected_provider_data(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'canonical-report.db'}"

    async def scenario() -> tuple[int, int, int, int, int]:
        engine = create_async_engine(database_url)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            sport = Sport(code="football", name="Association football")
            session.add(sport)
            await session.flush()
            competition = Competition(sport_id=sport.id, name="League", slug="league")
            session.add(competition)
            await session.flush()
            season = Season(competition_id=competition.id, name="2026")
            home = Team(sport_id=sport.id, name="Home", slug="home")
            away = Team(sport_id=sport.id, name="Away", slug="away")
            session.add_all([season, home, away])
            await session.flush()
            fixture = Fixture(
                competition_id=competition.id,
                season_id=season.id,
                home_team_id=home.id,
                away_team_id=away.id,
                kickoff_at=datetime(2026, 8, 1, tzinfo=UTC),
                status="finished",
                home_score=2,
                away_score=0,
            )
            session.add(fixture)
            await session.flush()

            report = ProviderMatchDetails.model_validate(
                {
                    "external_id": "provider-fixture-1",
                    "kickoff_at": "2026-08-01T00:00:00Z",
                    "status": "finished",
                    "home_team": {
                        "external_id": "home-ext",
                        "lineup": [
                            {"external_id": "p-1", "name": "Starter", "position": "Forward"}
                        ],
                        "bench": [{"external_id": "p-2", "name": "Substitute"}],
                    },
                    "away_team": {"external_id": "away-ext"},
                    "goals": [
                        {"minute": 10, "scorer_external_id": "p-1"},
                        {"minute": 10, "scorer_external_id": "p-1"},
                    ],
                    "substitutions": [
                        {
                            "minute": 70,
                            "team_external_id": "home-ext",
                            "player_in_external_id": "p-2",
                            "player_in_name": "Substitute",
                            "player_out_external_id": "p-1",
                            "player_out_name": "Starter",
                        }
                    ],
                }
            )
            first_counts = await replace_canonical_fixture_report(
                session, provider="test-provider", fixture_id=fixture.id, report=report
            )
            await session.commit()
            second_counts = await replace_canonical_fixture_report(
                session, provider="test-provider", fixture_id=fixture.id, report=report
            )
            await session.commit()
            event_count = await session.scalar(
                select(func.count()).select_from(FixtureMatchEvent)
            )
            participation_count = await session.scalar(
                select(func.count()).select_from(FixturePlayerParticipation)
            )
            starter = await session.scalar(
                select(FixturePlayerParticipation).where(
                    FixturePlayerParticipation.player_external_id == "p-1"
                )
            )
            substitute = await session.scalar(
                select(FixturePlayerParticipation).where(
                    FixturePlayerParticipation.player_external_id == "p-2"
                )
            )

            corrected = report.model_copy(update={"goals": (), "substitutions": ()})
            await replace_canonical_fixture_report(
                session,
                provider="test-provider",
                fixture_id=fixture.id,
                report=corrected,
            )
            await session.commit()
            corrected_event_count = await session.scalar(
                select(func.count()).select_from(FixtureMatchEvent)
            )
            corrected_participation_count = await session.scalar(
                select(func.count()).select_from(FixturePlayerParticipation)
            )
            assert starter is not None and starter.is_starter and starter.appeared
            assert substitute is not None and substitute.appeared and substitute.is_bench
        await engine.dispose()
        return (
            first_counts[0],
            second_counts[0],
            int(event_count or 0),
            int(participation_count or 0),
            int(corrected_event_count or 0) + int(corrected_participation_count or 0),
        )

    first, second, events, participations, corrected_total = asyncio.run(scenario())
    assert first == second
    assert events == 3  # Two same-minute goals and one substitution.
    assert participations == 2
    assert corrected_total == 2  # The corrected report has only the two lineup records.
