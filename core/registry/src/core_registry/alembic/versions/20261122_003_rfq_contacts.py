"""Store consent-bearing responses and separately encrypted contact payloads."""

from alembic import op
import sqlalchemy as sa

revision = "20261122_003_rfq_contacts"
down_revision = "20261122_002_rfq_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rfq_responses",
        sa.Column("response_id", sa.String(128), primary_key=True),
        sa.Column("rfq_id", sa.String(128), nullable=False),
        sa.Column("respondent_namespace", sa.String(128), nullable=False),
        sa.Column("respondent_subject", sa.String(255), nullable=False),
        sa.Column("terms_revision", sa.Integer(), nullable=False),
        sa.Column("offered_quantity", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ("rfq_id", "terms_revision"),
            ("rfq_terms_revisions.rfq_id", "rfq_terms_revisions.revision"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ("rfq_id", "respondent_namespace", "respondent_subject"),
            ("rfq_party_references.rfq_id", "rfq_party_references.namespace", "rfq_party_references.subject"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "idx_rfq_responses_inbox", "rfq_responses", ["rfq_id", "created_at", "response_id"],
    )
    op.create_index(
        "uq_rfq_response_pending", "rfq_responses",
        ["rfq_id", "respondent_namespace", "respondent_subject", "terms_revision"], unique=True,
        sqlite_where=sa.text("state = 'pending'"), postgresql_where=sa.text("state = 'pending'"),
    )
    op.create_table(
        "rfq_introductions",
        sa.Column("introduction_id", sa.String(128), primary_key=True),
        sa.Column(
            "response_id", sa.String(128),
            sa.ForeignKey("rfq_responses.response_id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
        sa.Column("contact_until", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("response_id", name="uq_rfq_introduction_response"),
    )
    op.create_table(
        "rfq_contact_payloads",
        sa.Column(
            "response_id", sa.String(128),
            sa.ForeignKey("rfq_responses.response_id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("purpose", sa.String(32), primary_key=True),
        sa.Column("format_version", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.String(128), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "idx_rfq_contacts_expiry", "rfq_contact_payloads", ["expires_at", "response_id", "purpose"],
    )


def downgrade() -> None:
    raise NotImplementedError("RFQ consent and contact outcomes are retained; restore a backup instead")
