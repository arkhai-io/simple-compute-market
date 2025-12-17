"""add_owner_field

Revision ID: 002_add_owner_field
Revises: 001_initial
Create Date: 2025-12-10 19:01:29.338497

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002_add_owner_field'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('agents', sa.Column('owner', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('agents', 'owner')

