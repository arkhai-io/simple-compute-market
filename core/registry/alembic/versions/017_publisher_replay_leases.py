"""Add bounded attempt leases to publisher replay reservations.

Revision ID: 017_publisher_replay_leases
Revises: 016_marketplace_principal_auth
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "017_publisher_replay_leases"
down_revision = "016_marketplace_principal_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("publisher_replay_reservations") as batch_op:
        batch_op.add_column(sa.Column("lease_owner", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
        )
    op.execute(
        sa.text(
            "UPDATE publisher_replay_reservations "
            "SET lease_expires_at = created_at "
            "WHERE completed_at IS NULL"
        )
    )
    op.create_index(
        "idx_publisher_replay_lease_expires_at",
        "publisher_replay_reservations",
        ["lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_publisher_replay_lease_expires_at",
        table_name="publisher_replay_reservations",
    )
    with op.batch_alter_table("publisher_replay_reservations") as batch_op:
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("lease_owner")
