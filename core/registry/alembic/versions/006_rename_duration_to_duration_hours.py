"""rename_duration_to_duration_hours

Revision ID: 006_rename_duration_to_duration_hours
Revises: 005_simplify_to_erc8004_canonical_ids
Create Date: 2026-01-21 19:56:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "006_rename_duration_to_duration_hours"
down_revision = "005_simplify_to_erc8004_canonical_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "market_orders" not in inspector.get_table_names():
        return

    existing_columns = [col["name"] for col in inspector.get_columns("market_orders")]
    if "duration" in existing_columns and "duration_hours" not in existing_columns:
        with op.batch_alter_table("market_orders") as batch_op:
            batch_op.alter_column("duration", new_column_name="duration_hours")


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "market_orders" not in inspector.get_table_names():
        return

    existing_columns = [col["name"] for col in inspector.get_columns("market_orders")]
    if "duration_hours" in existing_columns and "duration" not in existing_columns:
        with op.batch_alter_table("market_orders") as batch_op:
            batch_op.alter_column("duration_hours", new_column_name="duration")
