"""Index canonical player analytics lookup paths.

Revision ID: 0010_player_analytics_indexes
Revises: 0009_canonical_match_events
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_player_analytics_indexes"
down_revision: str | None = "0009_canonical_match_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_fixture_match_events_secondary_player",
        "fixture_match_events",
        ["provider", "secondary_player_external_id"],
    )
    op.create_index(
        "ix_fixture_player_participation_team",
        "fixture_player_participation",
        ["provider", "team_external_id", "fixture_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_fixture_player_participation_team",
        table_name="fixture_player_participation",
    )
    op.drop_index(
        "ix_fixture_match_events_secondary_player",
        table_name="fixture_match_events",
    )
