"""standardize_agent_ids_and_metadata

Revision ID: 004_standardize_agent_ids_and_metadata
Revises: 003_add_market_orders_table
Create Date: 2025-12-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "004_standardize_agent_ids_and_metadata"
down_revision = "003_add_market_orders_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add integer autoincrement primary key and canonical ID column to agents table.
    with op.batch_alter_table("agents") as batch_op:
        batch_op.add_column(
            sa.Column("id", sa.Integer(), primary_key=False, autoincrement=True)
        )
        batch_op.add_column(
            sa.Column("agent_canonical_id", sa.String(), nullable=True)
        )

    # Backfill agent_canonical_id from existing agent_id values.
    agents_table = sa.table(
        "agents",
        sa.column("agent_id", sa.String()),
        sa.column("agent_canonical_id", sa.String()),
    )

    conn = op.get_bind()
    result = conn.execute(sa.select(agents_table.c.agent_id))
    rows = result.fetchall()
    for (agent_id,) in rows:
        conn.execute(
            agents_table.update()
            .where(agents_table.c.agent_id == agent_id)
            .values(agent_canonical_id=agent_id)
        )

    # Add unique index on agent_canonical_id for fast lookups.
    op.create_index(
        "ux_agents_agent_canonical_id",
        "agents",
        ["agent_canonical_id"],
        unique=True,
    )
    
    # Also add indexes on owner and token_uri for event sync lookups
    op.create_index("idx_agents_owner", "agents", ["owner"])
    op.create_index("idx_agents_token_uri", "agents", ["token_uri"])


def downgrade() -> None:
    # Drop indexes
    op.drop_index("idx_agents_token_uri", table_name="agents")
    op.drop_index("idx_agents_owner", table_name="agents")
    op.drop_index("ux_agents_agent_canonical_id", table_name="agents")
    
    # Drop new columns.
    with op.batch_alter_table("agents") as batch_op:
        batch_op.drop_column("agent_canonical_id")
        batch_op.drop_column("id")


