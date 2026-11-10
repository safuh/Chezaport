"""Add provider-neutral external identifier mappings.

Revision ID: 0005_external_id_mappings
Revises: 0004_sports_core
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_external_id_mappings"
down_revision: str | None = "0004_sports_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create provider-to-canonical entity mappings."""
    op.create_table(
        "external_id_mappings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=24), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("external_id", sa.String(length=160), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "entity_type IN ('sport', 'country', 'venue', 'competition', 'season', "
            "'team', 'player', 'fixture')",
            name="ck_external_mapping_entity_type_valid",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "entity_type", "external_id",
            name="uq_external_mapping_provider_external",
        ),
        sa.UniqueConstraint(
            "provider", "entity_type", "entity_id",
            name="uq_external_mapping_provider_entity",
        ),
    )
    op.create_index(
        "ix_external_id_mappings_entity",
        "external_id_mappings",
        ["entity_type", "entity_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove provider-to-canonical entity mappings."""
    op.drop_index("ix_external_id_mappings_entity", table_name="external_id_mappings")
    op.drop_table("external_id_mappings")
