"""Create provider-neutral core sports tables.

Revision ID: 0004_sports_core
Revises: 0003_refresh_tokens
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_sports_core"
down_revision: str | None = "0003_refresh_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the core sports domain schema."""
    op.create_table(
        "sports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "countries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=3), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "venues",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("country_id", sa.String(length=36), nullable=True),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "capacity IS NULL OR capacity >= 0", name="ck_venues_capacity_nonnegative"
        ),
        sa.ForeignKeyConstraint(["country_id"], ["countries.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_venues_country_id", "venues", ["country_id"], unique=False)
    op.create_table(
        "competitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sport_id", sa.String(length=36), nullable=False),
        sa.Column("country_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=180), nullable=False),
        sa.Column("competition_type", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["country_id"], ["countries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sport_id"], ["sports.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sport_id", "slug", name="uq_competitions_sport_slug"),
    )
    op.create_index("ix_competitions_country_id", "competitions", ["country_id"], unique=False)
    op.create_table(
        "seasons",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("competition_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="ck_seasons_date_order",
        ),
        sa.ForeignKeyConstraint(["competition_id"], ["competitions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("competition_id", "name", name="uq_seasons_competition_name"),
    )
    op.create_index("ix_seasons_competition_id", "seasons", ["competition_id"], unique=False)
    op.create_table(
        "teams",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sport_id", sa.String(length=36), nullable=False),
        sa.Column("country_id", sa.String(length=36), nullable=True),
        sa.Column("venue_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=180), nullable=False),
        sa.Column("short_name", sa.String(length=40), nullable=True),
        sa.Column("founded_year", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["country_id"], ["countries.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sport_id"], ["sports.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sport_id", "slug", name="uq_teams_sport_slug"),
    )
    op.create_index("ix_teams_country_id", "teams", ["country_id"], unique=False)
    op.create_table(
        "players",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("country_id", sa.String(length=36), nullable=True),
        sa.Column("first_name", sa.String(length=100), nullable=True),
        sa.Column("last_name", sa.String(length=100), nullable=True),
        sa.Column("display_name", sa.String(length=180), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("position", sa.String(length=40), nullable=True),
        sa.ForeignKeyConstraint(["country_id"], ["countries.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_players_country_id", "players", ["country_id"], unique=False)
    op.create_table(
        "team_memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("team_id", sa.String(length=36), nullable=False),
        sa.Column("player_id", sa.String(length=36), nullable=False),
        sa.Column("joined_on", sa.Date(), nullable=True),
        sa.Column("left_on", sa.Date(), nullable=True),
        sa.Column("shirt_number", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "left_on IS NULL OR joined_on IS NULL OR left_on >= joined_on",
            name="ck_team_memberships_date_order",
        ),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "team_id", "player_id", "joined_on", name="uq_team_memberships_registration"
        ),
    )
    op.create_index("ix_team_memberships_player_id", "team_memberships", ["player_id"], unique=False)
    op.create_index("ix_team_memberships_team_id", "team_memberships", ["team_id"], unique=False)
    op.create_table(
        "fixtures",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("competition_id", sa.String(length=36), nullable=False),
        sa.Column("season_id", sa.String(length=36), nullable=False),
        sa.Column("home_team_id", sa.String(length=36), nullable=False),
        sa.Column("away_team_id", sa.String(length=36), nullable=False),
        sa.Column("venue_id", sa.String(length=36), nullable=True),
        sa.Column("kickoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("home_score", sa.Integer(), nullable=True),
        sa.Column("away_score", sa.Integer(), nullable=True),
        sa.Column("round_name", sa.String(length=80), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "home_team_id <> away_team_id", name="ck_fixtures_distinct_teams"
        ),
        sa.CheckConstraint(
            "home_score IS NULL OR home_score >= 0",
            name="ck_fixtures_home_score_nonnegative",
        ),
        sa.CheckConstraint(
            "away_score IS NULL OR away_score >= 0",
            name="ck_fixtures_away_score_nonnegative",
        ),
        sa.ForeignKeyConstraint(["away_team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["competition_id"], ["competitions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["home_team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fixtures_kickoff_at", "fixtures", ["kickoff_at"], unique=False)
    op.create_index(
        "ix_fixtures_competition_season",
        "fixtures",
        ["competition_id", "season_id"],
        unique=False,
    )
    op.create_index("ix_fixtures_home_team_id", "fixtures", ["home_team_id"], unique=False)
    op.create_index("ix_fixtures_away_team_id", "fixtures", ["away_team_id"], unique=False)


def downgrade() -> None:
    """Drop sports tables in reverse dependency order."""
    op.drop_index("ix_fixtures_away_team_id", table_name="fixtures")
    op.drop_index("ix_fixtures_home_team_id", table_name="fixtures")
    op.drop_index("ix_fixtures_competition_season", table_name="fixtures")
    op.drop_index("ix_fixtures_kickoff_at", table_name="fixtures")
    op.drop_table("fixtures")
    op.drop_index("ix_team_memberships_team_id", table_name="team_memberships")
    op.drop_index("ix_team_memberships_player_id", table_name="team_memberships")
    op.drop_table("team_memberships")
    op.drop_index("ix_players_country_id", table_name="players")
    op.drop_table("players")
    op.drop_index("ix_teams_country_id", table_name="teams")
    op.drop_table("teams")
    op.drop_index("ix_seasons_competition_id", table_name="seasons")
    op.drop_table("seasons")
    op.drop_index("ix_competitions_country_id", table_name="competitions")
    op.drop_table("competitions")
    op.drop_index("ix_venues_country_id", table_name="venues")
    op.drop_table("venues")
    op.drop_table("countries")
    op.drop_table("sports")
