"""Rename market_orders → listings; column renames to listings vocabulary.

Revision ID: 008_rename_orders_to_listings
Revises: 007_add_oracle_address
Create Date: 2026-04-30 00:00:00.000000

Wire-level rename slice (slices 2-3) introduced HTTP-boundary translation
shims that mapped ``listing_id``/``seller``/``buyer``/``seller_attestation``/
``buyer_attestation`` (wire) to ``order_id``/``order_maker``/``order_taker``/
``maker_attestation``/``taker_attestation`` (DB columns). This migration
flips the DB so the shims can be retired in the same commit.

PostgreSQL also renames the enum type ``orderstatusenum`` → ``liststatusenum``
and its indexes ``idx_market_orders_*`` → ``idx_listings_*``.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "008_rename_orders_to_listings"
down_revision = "007_add_oracle_address"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name if bind and bind.dialect else None

    # Indexes off first; rename the table; rename columns; recreate indexes
    op.drop_index("idx_market_orders_agent_id", table_name="market_orders")
    op.drop_index("idx_market_orders_status", table_name="market_orders")
    op.drop_index("idx_market_orders_created_at", table_name="market_orders")

    op.rename_table("market_orders", "listings")

    op.alter_column("listings", "order_id", new_column_name="listing_id")
    op.alter_column("listings", "order_maker", new_column_name="seller")
    op.alter_column("listings", "order_taker", new_column_name="buyer")
    op.alter_column("listings", "maker_attestation", new_column_name="seller_attestation")
    op.alter_column("listings", "taker_attestation", new_column_name="buyer_attestation")

    op.create_index("idx_listings_agent_id", "listings", ["agent_id"])
    op.create_index("idx_listings_status", "listings", ["status"])
    op.create_index("idx_listings_created_at", "listings", ["created_at"])

    if dialect == "postgresql":
        op.execute("ALTER TYPE orderstatusenum RENAME TO liststatusenum")


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name if bind and bind.dialect else None

    if dialect == "postgresql":
        op.execute("ALTER TYPE liststatusenum RENAME TO orderstatusenum")

    op.drop_index("idx_listings_created_at", table_name="listings")
    op.drop_index("idx_listings_status", table_name="listings")
    op.drop_index("idx_listings_agent_id", table_name="listings")

    op.alter_column("listings", "buyer_attestation", new_column_name="taker_attestation")
    op.alter_column("listings", "seller_attestation", new_column_name="maker_attestation")
    op.alter_column("listings", "buyer", new_column_name="order_taker")
    op.alter_column("listings", "seller", new_column_name="order_maker")
    op.alter_column("listings", "listing_id", new_column_name="order_id")

    op.rename_table("listings", "market_orders")

    op.create_index("idx_market_orders_created_at", "market_orders", ["created_at"])
    op.create_index("idx_market_orders_status", "market_orders", ["status"])
    op.create_index("idx_market_orders_agent_id", "market_orders", ["agent_id"])
