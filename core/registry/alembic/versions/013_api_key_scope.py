"""api_keys: read/write scope column.

Revision ID: 013_api_key_scope
Revises: 012_pluggable_identity_scheme
Create Date: 2026-05-28 00:00:00.000000

Adds ``scope`` ('read' | 'write') to the ``api_keys`` table so the
registry can distinguish buyer (read) from seller (write) credentials.
A write key implies read.

The ``api_keys`` table is created by ``create_all`` at app startup, not
by a migration, so this step is guarded: on a database where the table
does not yet exist, ``create_all`` will build it with the ``scope``
column from the model and this migration no-ops; on a database that
already has the column it also no-ops. The migration does real work only
for an existing pre-split ``api_keys`` table, whose keys were full-access
and are backfilled to ``write`` to preserve that. The column default is
``read`` (least privilege) for future direct inserts; the application
sets the scope explicitly at mint time.
"""

import sqlalchemy as sa
from alembic import op


revision = "013_api_key_scope"
down_revision = "012_pluggable_identity_scheme"
branch_labels = None
depends_on = None


def _columns(inspector, table: str) -> set[str]:
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "api_keys" not in inspector.get_table_names():
        return
    if "scope" in _columns(inspector, "api_keys"):
        return
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.add_column(
            sa.Column("scope", sa.String(), nullable=False, server_default="read")
        )
    # Pre-existing keys were full-access; preserve that as write scope.
    op.execute("UPDATE api_keys SET scope = 'write'")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "api_keys" not in inspector.get_table_names():
        return
    if "scope" not in _columns(inspector, "api_keys"):
        return
    with op.batch_alter_table("api_keys") as batch_op:
        batch_op.drop_column("scope")
