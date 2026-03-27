"""add_oracle_address

Revision ID: 007_add_oracle_address
Revises: 006_rename_duration_to_duration_hours
Create Date: 2026-03-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "007_add_oracle_address"
down_revision = "006_rename_duration_to_duration_hours"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("market_orders", sa.Column("oracle_address", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("market_orders", "oracle_address")
