"""Add durable sports synchronization run history.

Revision ID: 0006_sports_sync_runs
Revises: 0005_external_id_mappings
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_sports_sync_runs"
down_revision: str | None = "0005_external_id_mappings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create synchronization audit history and freshness indexes."""
    op.create_table(
        "sports_sync_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("resource", sa.String(length=32), nullable=False),
        sa.Column("competition_code", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unchanged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'partial', 'failed')",
            name="ck_sports_sync_runs_status_valid",
        ),
        sa.CheckConstraint(
            "records_fetched >= 0 AND records_seen >= 0 AND created >= 0 "
            "AND updated >= 0 AND unchanged >= 0 AND failed >= 0",
            name="ck_sports_sync_runs_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ck_sports_sync_runs_time_order",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sports_sync_runs_started_at", "sports_sync_runs", ["started_at"])
    op.create_index(
        "ix_sports_sync_runs_provider_resource",
        "sports_sync_runs",
        ["provider", "resource", "started_at"],
    )


def downgrade() -> None:
    """Remove synchronization history."""
    op.drop_index("ix_sports_sync_runs_provider_resource", table_name="sports_sync_runs")
    op.drop_index("ix_sports_sync_runs_started_at", table_name="sports_sync_runs")
    op.drop_table("sports_sync_runs")
