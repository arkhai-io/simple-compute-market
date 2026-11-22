"""Store account-authenticated RFQ request bindings and mutation receipts."""

from alembic import op
import sqlalchemy as sa

revision = "20261122_001_rfq_receipts"
down_revision = "20261106_001_registry_retained_publications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rfq_replay_reservations",
        sa.Column("namespace", sa.String(128), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("key_id", sa.String(128), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("receipt", sa.JSON(none_as_null=True), nullable=True),
        sa.PrimaryKeyConstraint("namespace", "subject", "request_id"),
    )


def downgrade() -> None:
    raise NotImplementedError("RFQ request bindings are retained; restore a backup instead")
