"""Add mechanism-neutral settlement options to listings.

Revision ID: 015_listing_settlement_options
Revises: 014_agent_to_publisher
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "015_listing_settlement_options"
down_revision = "014_agent_to_publisher"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "listings",
        sa.Column("settlement_options", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("listings", "settlement_options")
