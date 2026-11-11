"""Retain opaque listing documents and authenticated seller evidence.

Revision ID: 20261106_001_registry_retained_publications
Revises: v0_3_0_baseline
"""

from alembic import op
import sqlalchemy as sa

revision = "20261106_001_registry_retained_publications"
down_revision = "v0_3_0_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("listings", sa.Column("published_document", sa.JSON(), nullable=True))
    op.add_column("listings", sa.Column("publisher_publication", sa.JSON(), nullable=True))
    op.add_column("listings", sa.Column("publisher_updates", sa.JSON(), nullable=True))


def downgrade() -> None:
    # Dropping these columns would discard every retained document and seller
    # proof, which the carrier columns cannot rebuild.
    raise NotImplementedError(
        "retained publications are not downgraded; restore a backup instead"
    )
