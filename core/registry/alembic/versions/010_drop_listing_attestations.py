"""listings: drop per-deal attestation columns.

Revision ID: 010_drop_listing_attestations
Revises: 009_listing_max_duration_seconds
Create Date: 2026-05-15 00:00:00.000000

``seller_attestation`` and ``buyer_attestation`` were per-deal data
hung off the listings table — a legacy of the pre-A2A two-listings-per-
deal era where the registry mirrored attestations between paired
buyer/seller listings. Under the current design listings are reusable
(many deals per listing) and a single deal can attach multiple escrows
(payment, bond, penalty). Per-deal facts live on the storefront's
``escrows`` table; the registry is purely a discovery surface and no
longer carries deal-outcome columns.

The ``/api/v1/system/stats/attestations`` endpoint that read these
columns is removed in the same change.
"""

from alembic import op


revision = "010_drop_listing_attestations"
down_revision = "009_listing_max_duration_seconds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("listings", "seller_attestation")
    op.drop_column("listings", "buyer_attestation")


def downgrade() -> None:
    import sqlalchemy as sa
    op.add_column(
        "listings",
        sa.Column("seller_attestation", sa.Text(), nullable=True),
    )
    op.add_column(
        "listings",
        sa.Column("buyer_attestation", sa.Text(), nullable=True),
    )
