"""listings: rename duration_hours → max_duration_seconds (NULL = unlimited).

Revision ID: 009_listing_max_duration_seconds
Revises: 008_rename_orders_to_listings
Create Date: 2026-04-30 00:00:00.000000

Cold-cut: existing rows had `duration_hours INTEGER NOT NULL` (typically
stored as 1 by callers using the publish-time default). We drop that
column and add a nullable `max_duration_seconds INTEGER`. Existing
listings become "unlimited duration ceiling" — semantically equivalent
to the old behavior since the buyer-supplied duration takes over from
this slice onward (Slice C wiring) and the max ceiling is advisory.

If you need to preserve the old per-listing hours (rare; they were
always defaulted to 1 in practice), seed `max_duration_seconds = 3600`
on existing rows before applying.
"""

from alembic import op
import sqlalchemy as sa


revision = "009_listing_max_duration_seconds"
down_revision = "008_rename_orders_to_listings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "listings",
        sa.Column("max_duration_seconds", sa.Integer(), nullable=True),
    )
    op.drop_column("listings", "duration_hours")


def downgrade() -> None:
    op.add_column(
        "listings",
        sa.Column("duration_hours", sa.Integer(), nullable=True),
    )
    op.drop_column("listings", "max_duration_seconds")
    # Old schema had NOT NULL; tests / callers must seed before re-tightening.
