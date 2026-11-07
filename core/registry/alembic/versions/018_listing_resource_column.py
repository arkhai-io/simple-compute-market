"""Rename listings.offer_resource → listings.listing_resource.

Revision ID: 018_listing_resource_column
Revises: 017_publisher_replay_leases

A seller's published shape is a listing; ``listing_resource`` names a negotiation message
either party sends. The column is renamed rather than mapped at the boundary
because a search for the retired name across the codebase is this rename's
verification strategy, and a surviving column keeps producing hits an auditor
has to dismiss one at a time.

``batch_alter_table`` covers SQLite, which has no ``ALTER COLUMN RENAME`` before
3.25 and is the dialect local development uses; on PostgreSQL it resolves to a
plain rename.
"""

from __future__ import annotations

from alembic import op

revision = "018_listing_resource_column"
down_revision = "017_publisher_replay_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("listings") as batch_op:
        batch_op.alter_column("offer_resource", new_column_name="listing_resource")


def downgrade() -> None:
    with op.batch_alter_table("listings") as batch_op:
        batch_op.alter_column("listing_resource", new_column_name="offer_resource")
