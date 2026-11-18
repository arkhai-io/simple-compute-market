"""Add nullable seller-authored listing details."""

import sqlalchemy as sa
from alembic import op

revision = "019_listing_details"
down_revision = "018_listing_resource_column"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("listings", sa.Column("title", sa.String(200), nullable=True))
    op.add_column("listings", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("listings", sa.Column("listing_metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("listings") as batch_op:
        batch_op.drop_column("listing_metadata")
        batch_op.drop_column("description")
        batch_op.drop_column("title")
