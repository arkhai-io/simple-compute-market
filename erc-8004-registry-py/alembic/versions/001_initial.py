"""Initial migration

Revision ID: 001_initial
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create agents table
    op.create_table(
        'agents',
        sa.Column('agent_id', sa.String(), nullable=False),
        sa.Column('chain_id', sa.Integer(), nullable=False),
        sa.Column('registry_address', sa.String(), nullable=False),
        sa.Column('token_uri', sa.Text(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('health_status', sa.Enum('healthy', 'stale', 'unreachable', 'deprecated', name='agentstatusenum'), nullable=False),
        sa.Column('last_heartbeat', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('agent_id')
    )
    op.create_index('idx_agents_chain_id', 'agents', ['chain_id'])
    op.create_index('idx_agents_health_status', 'agents', ['health_status'])

    # Create agent_metadata table
    op.create_table(
        'agent_metadata',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('agent_id', sa.String(), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('value', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_agent_metadata_agent_id', 'agent_metadata', ['agent_id'])

    # Create health_checks table
    op.create_table(
        'health_checks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('agent_id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('response_time', sa.Integer(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.agent_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_health_checks_agent_id', 'health_checks', ['agent_id'])
    op.create_index('idx_health_checks_checked_at', 'health_checks', ['checked_at'])


def downgrade() -> None:
    op.drop_index('idx_health_checks_checked_at', table_name='health_checks')
    op.drop_index('idx_health_checks_agent_id', table_name='health_checks')
    op.drop_table('health_checks')
    op.drop_index('idx_agent_metadata_agent_id', table_name='agent_metadata')
    op.drop_table('agent_metadata')
    op.drop_index('idx_agents_health_status', table_name='agents')
    op.drop_index('idx_agents_chain_id', table_name='agents')
    op.drop_table('agents')
