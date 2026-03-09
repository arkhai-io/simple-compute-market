"""add_market_orders_table

Revision ID: 003_add_market_orders_table
Revises: 002_add_owner_field
Create Date: 2025-12-15 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '003_add_market_orders_table'
down_revision = '002_add_owner_field'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create OrderStatusEnum (PostgreSQL only; SQLite doesn't support CREATE TYPE)
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind and bind.dialect else None

    if dialect_name == "postgresql":
        op.execute("CREATE TYPE orderstatusenum AS ENUM ('open', 'closed', 'accepted', 'expired')")
    
    # Create market_orders table
    op.create_table(
        'market_orders',
        sa.Column('order_id', sa.String(), nullable=False),
        sa.Column('agent_id', sa.String(), nullable=False),
        sa.Column('order_maker', sa.Text(), nullable=False),
        sa.Column('order_taker', sa.Text(), nullable=True),
        sa.Column('offer_resource', sa.JSON(), nullable=False),
        sa.Column('demand_resource', sa.JSON(), nullable=False),
        sa.Column('duration', sa.Integer(), nullable=False),
        sa.Column('maker_attestation', sa.Text(), nullable=True),
        sa.Column('taker_attestation', sa.Text(), nullable=True),
        sa.Column('status', sa.Enum('open', 'closed', 'accepted', 'expired', name='orderstatusenum'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('order_id')
    )
    op.create_index('idx_market_orders_agent_id', 'market_orders', ['agent_id'])
    op.create_index('idx_market_orders_status', 'market_orders', ['status'])
    op.create_index('idx_market_orders_created_at', 'market_orders', ['created_at'])


def downgrade() -> None:
    op.drop_index('idx_market_orders_created_at', table_name='market_orders')
    op.drop_index('idx_market_orders_status', table_name='market_orders')
    op.drop_index('idx_market_orders_agent_id', table_name='market_orders')
    op.drop_table('market_orders')

    # Drop PostgreSQL enum type if it exists
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind and bind.dialect else None
    if dialect_name == "postgresql":
        op.execute("DROP TYPE orderstatusenum")

