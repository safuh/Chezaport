"""Persist normalized provider match-report snapshots.

Revision ID: 0008_fixture_report_snapshots
Revises: 0007_identity_roles
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_fixture_report_snapshots"
down_revision: str | None = "0007_identity_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fixture_report_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("fixture_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("external_id", sa.String(length=160), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["fixture_id"], ["fixtures.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "fixture_id", name="uq_fixture_report_provider_fixture"),
    )
    op.create_index(
        "ix_fixture_report_snapshots_fetched_at", "fixture_report_snapshots", ["fetched_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_fixture_report_snapshots_fetched_at", table_name="fixture_report_snapshots")
    op.drop_table("fixture_report_snapshots")
