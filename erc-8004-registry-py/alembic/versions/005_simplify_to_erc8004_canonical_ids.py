"""simplify_to_erc8004_canonical_ids

Revision ID: 005_simplify_to_erc8004_canonical_ids
Revises: 004_standardize_agent_ids_and_metadata
Create Date: 2025-12-16 05:03:44.498514

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '005_simplify_to_erc8004_canonical_ids'
down_revision = '004_standardize_agent_ids_and_metadata'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Check if columns already exist (for databases that were partially migrated)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = [col['name'] for col in inspector.get_columns('agents')]
    
    # Add new columns for ERC-8004 canonical ID components
    with op.batch_alter_table("agents") as batch_op:
        # Add onchain_agent_id (numeric tokenId from ERC-721) if it doesn't exist
        if "onchain_agent_id" not in existing_columns:
            batch_op.add_column(
                sa.Column("onchain_agent_id", sa.Integer(), nullable=True)
            )
        # Add identity_registry (registry contract address) if it doesn't exist
        if "identity_registry" not in existing_columns:
            batch_op.add_column(
                sa.Column("identity_registry", sa.String(), nullable=True)
            )
    
    # For existing agents, try to extract components from agent_canonical_id or agent_id
    # Since user indicated fresh reset is acceptable, we'll clear old data
    # New registrations will populate these fields correctly
    agents_table = sa.table(
        "agents",
        sa.column("agent_id", sa.String()),
        sa.column("agent_canonical_id", sa.String()),
        sa.column("chain_id", sa.Integer()),
        sa.column("registry_address", sa.String()),
        sa.column("onchain_agent_id", sa.Integer()),
        sa.column("identity_registry", sa.String()),
    )
    
    conn = op.get_bind()
    # Clear agent_id to prepare for canonical format (fresh reset approach)
    # New registrations will populate with eip155:... format
    conn.execute(
        agents_table.update().values(agent_id=None)
    )
    
    # Copy registry_address to identity_registry for existing rows
    conn.execute(
        sa.text("UPDATE agents SET identity_registry = registry_address WHERE registry_address IS NOT NULL")
    )
    
    # Drop index on agent_canonical_id before dropping the column (if it exists)
    existing_indexes = [idx['name'] for idx in inspector.get_indexes('agents')]
    if "ux_agents_agent_canonical_id" in existing_indexes:
        op.drop_index("ux_agents_agent_canonical_id", table_name="agents")
    
    # Drop agent_canonical_id column (redundant - agent_id will be canonical) if it exists
    if "agent_canonical_id" in existing_columns:
        with op.batch_alter_table("agents") as batch_op:
            batch_op.drop_column("agent_canonical_id")
    
    # Make agent_id NOT NULL after migration (new registrations must provide canonical ID)
    # But first make it nullable temporarily to allow the migration
    # We'll make it required in the model, but allow NULL during transition
    
    # Get updated list of indexes after potential column drops
    existing_indexes_after = [idx['name'] for idx in inspector.get_indexes('agents')]
    
    # Add unique constraint on (chain_id, identity_registry, onchain_agent_id) for event sync lookups
    if "ux_agents_chain_registry_onchain" not in existing_indexes_after:
        op.create_index(
            "ux_agents_chain_registry_onchain",
            "agents",
            ["chain_id", "identity_registry", "onchain_agent_id"],
            unique=True,
        )
    
    # Add index on identity_registry for faster lookups
    if "idx_agents_identity_registry" not in existing_indexes_after:
        op.create_index(
            "idx_agents_identity_registry",
            "agents",
            ["identity_registry"],
        )
    
    # Add index on onchain_agent_id for faster lookups
    if "idx_agents_onchain_agent_id" not in existing_indexes_after:
        op.create_index(
            "idx_agents_onchain_agent_id",
            "agents",
            ["onchain_agent_id"],
        )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("idx_agents_onchain_agent_id", table_name="agents")
    op.drop_index("idx_agents_identity_registry", table_name="agents")
    op.drop_index("ux_agents_chain_registry_onchain", table_name="agents")
    
    # Re-add agent_canonical_id column
    with op.batch_alter_table("agents") as batch_op:
        batch_op.add_column(
            sa.Column("agent_canonical_id", sa.String(), nullable=True)
        )
    
    # Recreate index on agent_canonical_id
    op.create_index(
        "ux_agents_agent_canonical_id",
        "agents",
        ["agent_canonical_id"],
        unique=True,
    )
    
    # Drop new columns
    with op.batch_alter_table("agents") as batch_op:
        batch_op.drop_column("identity_registry")
        batch_op.drop_column("onchain_agent_id")

