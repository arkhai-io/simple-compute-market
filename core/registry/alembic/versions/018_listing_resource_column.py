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
import sqlalchemy as sa

revision = "018_listing_resource_column"
down_revision = "017_publisher_replay_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("listings")}
    # Both fresh-chain schemas and deployed schemas must reach the same head;
    # a schema carrying both names is ambiguous and cannot be renamed safely.
    if "listing_resource" in columns:
        if "offer_resource" in columns:
            raise RuntimeError("listings has both listing_resource and offer_resource")
        return
    with op.batch_alter_table("listings") as batch_op:
        batch_op.alter_column("offer_resource", new_column_name="listing_resource")


def downgrade() -> None:
    with op.batch_alter_table("listings") as batch_op:
        batch_op.alter_column("listing_resource", new_column_name="offer_resource")
