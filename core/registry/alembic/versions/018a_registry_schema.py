"""Ensure registry migrations provide listing demands and API-key storage."""

from alembic import op
import sqlalchemy as sa

revision = "018a_registry_schema"
down_revision = "018_listing_resource_column"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("listings")}
    if "demands" not in columns:
        op.add_column("listings", sa.Column("demands", sa.JSON(), nullable=True))
    if "api_keys" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "api_keys",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("key_hash", sa.String(), nullable=False, unique=True),
            sa.Column("scope", sa.String(), nullable=False, server_default="read"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("idx_api_keys_revoked_at", "api_keys", ["revoked_at"])


def downgrade() -> None:
    # These schema-compatibility carriers may predate the revision on a
    # deployed registry. Never discard their data on a compatibility rollback.
    pass
