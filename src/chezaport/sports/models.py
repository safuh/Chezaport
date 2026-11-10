"""Persistence models for the core sports domain.

The models deliberately contain provider-neutral fields only. Provider IDs and
provider-specific payloads belong in the integration layer, not these tables.
"""

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from chezaport.core.database import Base


def _new_id() -> str:
    """Return a portable UUID string primary key."""
    return str(uuid4())


class Sport(Base):
    """A sport supported by the platform, such as association football."""

    __tablename__ = "sports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Country(Base):
    """A country or territory used for competition and participant metadata."""

    __tablename__ = "countries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    code: Mapped[str | None] = mapped_column(String(3), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)


class Venue(Base):
    """A physical venue where a fixture can be played."""

    __tablename__ = "venues"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("countries.id", ondelete="SET NULL"), nullable=True
    )
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    __table_args__ = (
        CheckConstraint("capacity IS NULL OR capacity >= 0", name="ck_venues_capacity_nonnegative"),
        Index("ix_venues_country_id", "country_id"),
    )


class Competition(Base):
    """A league, cup, tournament, or other organized competition."""

    __tablename__ = "competitions"
    __table_args__ = (
        UniqueConstraint("sport_id", "slug", name="uq_competitions_sport_slug"),
        Index("ix_competitions_country_id", "country_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    sport_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sports.id", ondelete="RESTRICT"), nullable=False
    )
    country_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("countries.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), nullable=False)
    competition_type: Mapped[str] = mapped_column(String(32), nullable=False, default="league")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Season(Base):
    """A competition edition spanning a defined date range."""

    __tablename__ = "seasons"
    __table_args__ = (
        UniqueConstraint("competition_id", "name", name="uq_seasons_competition_name"),
        CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="ck_seasons_date_order",
        ),
        Index("ix_seasons_competition_id", "competition_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    competition_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("competitions.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Team(Base):
    """A team participating in a sport and its competitions."""

    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("sport_id", "slug", name="uq_teams_sport_slug"),
        Index("ix_teams_country_id", "country_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    sport_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sports.id", ondelete="RESTRICT"), nullable=False
    )
    country_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("countries.id", ondelete="SET NULL"), nullable=True
    )
    venue_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("venues.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    founded_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Player(Base):
    """A player profile independent of any one team registration."""

    __tablename__ = "players"
    __table_args__ = (Index("ix_players_country_id", "country_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    country_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("countries.id", ondelete="SET NULL"), nullable=True
    )
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    display_name: Mapped[str] = mapped_column(String(180), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    position: Mapped[str | None] = mapped_column(String(40), nullable=True)


class TeamMembership(Base):
    """A player's time-bounded registration with a team.

    Keeping memberships separate preserves transfer history instead of
    overwriting a player's previous team whenever a transfer occurs.
    """

    __tablename__ = "team_memberships"
    __table_args__ = (
        UniqueConstraint(
            "team_id", "player_id", "joined_on", name="uq_team_memberships_registration"
        ),
        CheckConstraint(
            "left_on IS NULL OR joined_on IS NULL OR left_on >= joined_on",
            name="ck_team_memberships_date_order",
        ),
        Index("ix_team_memberships_player_id", "player_id"),
        Index("ix_team_memberships_team_id", "team_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    team_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )
    player_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("players.id", ondelete="CASCADE"), nullable=False
    )
    joined_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    left_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    shirt_number: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Fixture(Base):
    """A scheduled or completed match between two teams."""

    __tablename__ = "fixtures"
    __table_args__ = (
        CheckConstraint("home_team_id <> away_team_id", name="ck_fixtures_distinct_teams"),
        CheckConstraint(
            "home_score IS NULL OR home_score >= 0", name="ck_fixtures_home_score_nonnegative"
        ),
        CheckConstraint(
            "away_score IS NULL OR away_score >= 0", name="ck_fixtures_away_score_nonnegative"
        ),
        CheckConstraint(
            "status IN ('scheduled', 'live', 'halftime', 'finished', 'postponed', "
            "'suspended', 'abandoned', 'cancelled')",
            name="ck_fixtures_status_valid",
        ),
        Index("ix_fixtures_kickoff_at", "kickoff_at"),
        Index("ix_fixtures_competition_season", "competition_id", "season_id"),
        Index("ix_fixtures_home_team_id", "home_team_id"),
        Index("ix_fixtures_away_team_id", "away_team_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    competition_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("competitions.id", ondelete="RESTRICT"), nullable=False
    )
    season_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("seasons.id", ondelete="RESTRICT"), nullable=False
    )
    home_team_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    away_team_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    venue_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("venues.id", ondelete="SET NULL"), nullable=True
    )
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="scheduled")
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    round_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
