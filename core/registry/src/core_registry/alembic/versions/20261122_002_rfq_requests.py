"""Store RFQ requests, terms history and RFQ-scoped party references."""

from alembic import op
import sqlalchemy as sa

revision = "20261122_002_rfq_requests"
down_revision = "20261122_001_rfq_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rfq_requests",
        sa.Column("rfq_id", sa.String(128), primary_key=True),
        sa.Column("kind", sa.String(128), nullable=False),
        sa.Column("buyer_namespace", sa.String(128), nullable=False),
        sa.Column("buyer_subject", sa.String(255), nullable=False),
        sa.Column("requirements", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("terms_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("respond_by", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "idx_rfq_requests_discovery", "rfq_requests",
        ["kind", "closed_at", "created_at", "rfq_id"],
    )
    op.create_table(
        "rfq_terms_revisions",
        sa.Column(
            "rfq_id", sa.String(128),
            sa.ForeignKey("rfq_requests.rfq_id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("requirements", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "rfq_party_references",
        sa.Column(
            "rfq_id", sa.String(128),
            sa.ForeignKey("rfq_requests.rfq_id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("namespace", sa.String(128), primary_key=True),
        sa.Column("subject", sa.String(255), primary_key=True),
        sa.Column("reference", sa.String(128), nullable=False),
        sa.UniqueConstraint("rfq_id", "reference", name="uq_rfq_party_reference"),
    )


def downgrade() -> None:
    raise NotImplementedError("RFQ requests and their terms are retained; restore a backup instead")
