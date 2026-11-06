"""Retain opaque listing documents and authenticated seller evidence."""

from alembic import op
import sqlalchemy as sa

revision = "019_retained_publications"
down_revision = "v0_3_0_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("listings", sa.Column("published_document", sa.JSON(), nullable=True))
    op.add_column("listings", sa.Column("publisher_publication", sa.JSON(), nullable=True))
    op.add_column("listings", sa.Column("publisher_updates", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("listings") as batch:
        batch.drop_column("publisher_updates")
        batch.drop_column("publisher_publication")
        batch.drop_column("published_document")
