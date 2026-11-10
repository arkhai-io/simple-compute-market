"""The registry's supported baseline: its schema as the v0.3.0 release builds it.

Fixed operations, not the current models, so that a model edit never changes
what this revision creates: a later schema change is a later revision. A
database the v0.3.0 release built records ``018_listing_resource_column`` and
is adopted at this revision without running it (``core_registry.db.migrations``).
See openspec/specs/deployment-state/spec.md.

Revision ID: v0_3_0_baseline
Revises: none
"""

import sqlalchemy as sa
from alembic import op

revision = "v0_3_0_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "publishers",
        sa.Column("publisher_id", sa.Integer(), nullable=False),
        sa.Column("storefront_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("publisher_id"),
    )

    op.create_table(
        "publisher_replay_reservations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("principal_scheme", sa.String(), nullable=False),
        sa.Column("principal_identifier", sa.String(), nullable=False),
        sa.Column("request_id", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("lease_owner", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "principal_scheme",
            "principal_identifier",
            "request_id",
            name="uq_publisher_replay_principal_request",
        ),
    )
    op.create_index(
        "idx_publisher_replay_lease_expires_at",
        "publisher_replay_reservations",
        ["lease_expires_at"],
    )
    op.create_index(
        "idx_publisher_replay_created_at",
        "publisher_replay_reservations",
        ["created_at"],
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("key_hash", sa.String(), nullable=False),
        sa.Column(
            "scope", sa.String(), server_default=sa.text("'read'"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index("idx_api_keys_revoked_at", "api_keys", ["revoked_at"])

    op.create_table(
        "identities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("publisher_id", sa.Integer(), nullable=False),
        sa.Column("scheme", sa.String(), nullable=False),
        sa.Column("identifier", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.String(),
            server_default=sa.text("'primary'"),
            nullable=False,
        ),
        sa.Column("active_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["publisher_id"], ["publishers.publisher_id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ux_identities_scheme_identifier",
        "identities",
        ["scheme", "identifier"],
        unique=True,
    )
    op.create_index(
        "ux_identities_one_primary_per_publisher",
        "identities",
        ["publisher_id"],
        unique=True,
        sqlite_where=sa.text("status = 'primary'"),
        postgresql_where=sa.text("status = 'primary'"),
    )
    op.create_index("idx_identities_publisher_id", "identities", ["publisher_id"])

    op.create_table(
        "publisher_identity_rotations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("publisher_id", sa.Integer(), nullable=False),
        sa.Column("nonce", sa.String(), nullable=False),
        sa.Column("intent_hash", sa.String(), nullable=False),
        sa.Column("current_scheme", sa.String(), nullable=False),
        sa.Column("current_identifier", sa.String(), nullable=False),
        sa.Column("replacement_scheme", sa.String(), nullable=False),
        sa.Column("replacement_identifier", sa.String(), nullable=False),
        sa.Column("overlap_seconds", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "publisher_id", "nonce", name="uq_publisher_rotation_nonce"
        ),
        sa.ForeignKeyConstraint(
            ["publisher_id"], ["publishers.publisher_id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "idx_publisher_rotations_publisher_id",
        "publisher_identity_rotations",
        ["publisher_id"],
    )

    op.create_table(
        "listings",
        sa.Column("listing_id", sa.String(), nullable=False),
        sa.Column("publisher_id", sa.Integer(), nullable=False),
        sa.Column("listing_resource", sa.JSON(), nullable=False),
        sa.Column("accepted_escrows", sa.JSON(), nullable=True),
        sa.Column("settlement_options", sa.JSON(), nullable=True),
        sa.Column("demands", sa.JSON(), nullable=True),
        sa.Column("max_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("oracle_address", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("open", "closed", "expired", name="liststatusenum"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("listing_id"),
        sa.ForeignKeyConstraint(
            ["publisher_id"], ["publishers.publisher_id"], ondelete="CASCADE"
        ),
    )
    op.create_index("idx_listings_created_at", "listings", ["created_at"])
    op.create_index("idx_listings_publisher_id", "listings", ["publisher_id"])
    op.create_index("idx_listings_status", "listings", ["status"])


def downgrade() -> None:
    raise NotImplementedError(
        "the registry's baseline is not downgraded; restore a backup instead"
    )
