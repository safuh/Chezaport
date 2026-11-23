"""Seed a clearly synthetic, deterministic football dataset for demonstrations.

Usage: uv run python -m chezaport.sports.demo

The command never updates or deletes existing records. It exits unchanged when
its dedicated demo competition already exists.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from chezaport.core.config import get_settings
from chezaport.core.database import create_engine, create_session_factory, session_scope
from chezaport.sports.models import Competition, Fixture, Season, Sport, Team
from chezaport.sports.services.bootstrap import seed_default_sports

_DEMO_SLUG = "chezaport-synthetic-demo-league"
_TEAMS = (
    ("Harbour City FC", "harbour-city-fc"),
    ("Highland Rovers", "highland-rovers"),
    ("Lakeside Athletic", "lakeside-athletic"),
    ("Valley United", "valley-united"),
)
_MATCHES = (
    (0, 1, 2, 1, 1),
    (2, 3, 0, 0, 2),
    (0, 2, 1, 1, 3),
    (1, 3, 3, 1, 4),
    (0, 3, 2, 0, 5),
    (1, 2, 1, 2, 6),
)


async def seed_demo_dataset(session_factory) -> bool:
    """Create the synthetic demo league once; return whether it was created."""
    async with session_scope(session_factory) as session:
        await seed_default_sports(session)
        existing = await session.scalar(
            select(Competition.id).where(Competition.slug == _DEMO_SLUG)
        )
        if existing is not None:
            return False
        sport = await session.scalar(select(Sport).where(Sport.code == "football"))
        if sport is None:
            raise RuntimeError("football sport bootstrap did not create the canonical sport")
        competition = Competition(
            sport_id=sport.id,
            name="Synthetic Demonstration League (Fictional Data)",
            slug=_DEMO_SLUG,
            competition_type="league",
            is_active=True,
        )
        session.add(competition)
        await session.flush()
        season = Season(
            competition_id=competition.id,
            name="DEMO-2025",
            start_date=date(2025, 8, 1),
            end_date=date(2025, 9, 30),
            is_current=False,
        )
        session.add(season)
        teams = [
            Team(sport_id=sport.id, name=name, slug=slug, short_name=name[:3].upper())
            for name, slug in _TEAMS
        ]
        session.add_all(teams)
        await session.flush()
        for home_index, away_index, home_score, away_score, day in _MATCHES:
            session.add(
                Fixture(
                    competition_id=competition.id,
                    season_id=season.id,
                    home_team_id=teams[home_index].id,
                    away_team_id=teams[away_index].id,
                    kickoff_at=datetime(2025, 8, 1, 15, 0, tzinfo=UTC) + timedelta(days=day * 7),
                    status="finished",
                    home_score=home_score,
                    away_score=away_score,
                    round_name=f"Demo round {day}",
                )
            )
        await session.flush()
        return True


async def _run() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        created = await seed_demo_dataset(create_session_factory(engine))
        if created:
            print("Created synthetic demo league: 4 fictional teams, 6 completed fixtures.")
            print("Dataset label: Synthetic Demonstration League (Fictional Data).")
        else:
            print("Synthetic demo league already exists; no records were changed.")
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
