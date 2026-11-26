"""Persist canonical provider match events and player participation.

Revision ID: 0009_canonical_match_events
Revises: 0008_fixture_report_snapshots
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_canonical_match_events"
down_revision: str | None = "0008_fixture_report_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fixture_match_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("fixture_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("source_key", sa.String(length=220), nullable=False),
        sa.Column("minute", sa.Integer(), nullable=True),
        sa.Column("player_external_id", sa.String(length=160), nullable=True),
        sa.Column("secondary_player_external_id", sa.String(length=160), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["fixture_id"], ["fixtures.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "fixture_id", "source_key",
            name="uq_fixture_match_events_provider_fixture_source",
        ),
    )
    op.create_index(
        "ix_fixture_match_events_fixture_type",
        "fixture_match_events",
        ["fixture_id", "event_type"],
    )
    op.create_index(
        "ix_fixture_match_events_player",
        "fixture_match_events",
        ["provider", "player_external_id"],
    )
    op.create_table(
        "fixture_player_participation",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("fixture_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("player_external_id", sa.String(length=160), nullable=False),
        sa.Column("player_name", sa.String(length=180), nullable=True),
        sa.Column("team_external_id", sa.String(length=160), nullable=True),
        sa.Column("is_starter", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_bench", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("appeared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("position", sa.String(length=80), nullable=True),
        sa.Column("shirt_number", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["fixture_id"], ["fixtures.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "fixture_id", "player_external_id",
            name="uq_fixture_player_participation_provider_fixture_player",
        ),
    )
    op.create_index(
        "ix_fixture_player_participation_player",
        "fixture_player_participation",
        ["provider", "player_external_id"],
    )
    op.create_index(
        "ix_fixture_player_participation_fixture",
        "fixture_player_participation",
        ["fixture_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fixture_player_participation_fixture", table_name="fixture_player_participation"
    )
    op.drop_index(
        "ix_fixture_player_participation_player", table_name="fixture_player_participation"
    )
    op.drop_table("fixture_player_participation")
    op.drop_index("ix_fixture_match_events_player", table_name="fixture_match_events")
    op.drop_index("ix_fixture_match_events_fixture_type", table_name="fixture_match_events")
    op.drop_table("fixture_match_events")
