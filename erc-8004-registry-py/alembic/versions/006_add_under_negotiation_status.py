"""add_under_negotiation_status

Revision ID: 006_add_under_negotiation_status
Revises: 005_simplify_to_erc8004_canonical_ids
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '006_add_under_negotiation_status'
down_revision = '005_simplify_to_erc8004_canonical_ids'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add 'under_negotiation' status to OrderStatusEnum.
    
    This status represents orders that are in a negotiation cycle
    (price-different but resource-compatible matches).
    """
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind and bind.dialect else None

    if dialect_name == "postgresql":
        # PostgreSQL: Alter the enum type to add new value
        # Note: ALTER TYPE ... ADD VALUE cannot be run in a transaction block
        # We use a workaround by executing it directly
        op.execute("ALTER TYPE orderstatusenum ADD VALUE IF NOT EXISTS 'under_negotiation'")
    # SQLite: No change needed - status is stored as string, enum is enforced at application level


def downgrade() -> None:
    """Remove 'under_negotiation' status from OrderStatusEnum.
    
    Note: PostgreSQL doesn't support removing enum values easily.
    For a full downgrade, we'd need to:
    1. Update all 'under_negotiation' rows to 'open' or 'expired'
    2. Recreate the enum type without 'under_negotiation'
    3. Recreate the table column
    
    For now, we'll just update existing rows to 'open' as a safe fallback.
    """
    bind = op.get_bind()
    dialect_name = bind.dialect.name if bind and bind.dialect else None

    # Update any orders with 'under_negotiation' status to 'open'
    op.execute(
        sa.text("UPDATE market_orders SET status = 'open' WHERE status = 'under_negotiation'")
    )
    
    # Note: PostgreSQL enum removal is complex and requires recreating the type
    # For production, consider a more sophisticated downgrade strategy
    if dialect_name == "postgresql":
        # We don't remove the enum value in downgrade as it's complex
        # The application will handle the missing value gracefully
        pass

