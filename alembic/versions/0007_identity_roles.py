"""Add least-privilege application roles to user identities.

Revision ID: 0007_identity_roles
Revises: 0006_sports_sync_runs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_identity_roles"
down_revision: str | None = "0006_sports_sync_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("role", sa.String(length=16), nullable=False, server_default="viewer")
    )
    with op.batch_alter_table("users") as batch:
        batch.create_check_constraint(
            "ck_users_role_valid", "role IN ('viewer', 'operator', 'admin')"
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_role_valid", type_="check")
        batch.drop_column("role")
