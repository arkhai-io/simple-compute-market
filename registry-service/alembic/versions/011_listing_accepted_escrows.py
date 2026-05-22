"""listings: replace demand_resource with accepted_escrows.

Revision ID: 011_listing_accepted_escrows
Revises: 010_drop_listing_attestations
Create Date: 2026-05-15 00:00:00.000000

The storefront migrated to ``accepted_escrows`` in milestone b1; the
registry side stayed on the pre-b1 ``demand_resource`` shape until now,
with a back-translation shim on the storefront's publish path
(``_synthesize_demand_for_registry``). This migration drops the shim's
reason to exist by giving the registry the same wire/storage shape the
storefront uses natively. Discovery-state only — no per-deal data is
on the registry, so there's no backfill: storefronts re-publish on
their next update cycle and the column repopulates from authoritative
local state.
"""

import sqlalchemy as sa
from alembic import op


revision = "011_listing_accepted_escrows"
down_revision = "010_drop_listing_attestations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "listings",
        sa.Column("accepted_escrows", sa.JSON(), nullable=True),
    )
    op.drop_column("listings", "demand_resource")


def downgrade() -> None:
    op.add_column(
        "listings",
        sa.Column("demand_resource", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.drop_column("listings", "accepted_escrows")
