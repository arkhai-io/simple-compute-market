"""Validate and tag every legacy publisher owner as an EIP-191 principal.

Revision ID: 012_pluggable_identity_scheme
Revises: 011_listing_accepted_escrows
"""

from __future__ import annotations

import json
import re

import sqlalchemy as sa
from alembic import op

revision = "012_pluggable_identity_scheme"
down_revision = "011_listing_accepted_escrows"
branch_labels = None
depends_on = None

_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT agent_id, chain_id, identity_registry, onchain_agent_id, "
            "owner, token_uri FROM agents ORDER BY agent_id"
        )
    ).fetchall()

    validated: list[tuple[object, ...]] = []
    principals: set[str] = set()
    for row in rows:
        agent_id, chain_id, identity_registry, onchain_agent_id, owner, token_uri = row
        if not isinstance(agent_id, str) or not agent_id:
            raise RuntimeError("malformed legacy agent identifier")
        if not isinstance(owner, str) or not _ADDRESS.fullmatch(owner):
            raise RuntimeError("unknown or malformed legacy publisher owner")
        identifier = owner.lower()
        if identifier in principals:
            raise RuntimeError("duplicate canonical legacy publisher owner")
        principals.add(identifier)
        validated.append(
            (
                agent_id,
                identifier,
                chain_id,
                identity_registry,
                onchain_agent_id,
                token_uri,
            )
        )

    with op.batch_alter_table("agents") as batch_op:
        batch_op.add_column(sa.Column("scheme", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("identifier", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("scheme_metadata", sa.JSON(), nullable=True))

    for (
        agent_id,
        identifier,
        chain_id,
        identity_registry,
        onchain_agent_id,
        token_uri,
    ) in validated:
        metadata = {
            key: value
            for key, value in {
                "agent_id": agent_id,
                "chain_id": chain_id,
                "identity_registry": identity_registry,
                "onchain_agent_id": onchain_agent_id,
                "token_uri": token_uri,
            }.items()
            if value is not None
        }
        connection.execute(
            sa.text(
                "UPDATE agents SET scheme = :scheme, identifier = :identifier, "
                "scheme_metadata = :metadata WHERE agent_id = :agent_id"
            ),
            {
                "scheme": "eip191",
                "identifier": identifier,
                "metadata": json.dumps(metadata) if metadata else None,
                "agent_id": agent_id,
            },
        )

    with op.batch_alter_table("agents") as batch_op:
        batch_op.alter_column(
            "scheme",
            existing_type=sa.String(),
            nullable=False,
        )
        batch_op.alter_column(
            "identifier",
            existing_type=sa.String(),
            nullable=False,
        )
    op.create_index(
        "ux_agents_scheme_identifier",
        "agents",
        ["scheme", "identifier"],
        unique=True,
    )
    op.create_index("idx_agents_scheme", "agents", ["scheme"])


def downgrade() -> None:
    op.drop_index("idx_agents_scheme", table_name="agents")
    op.drop_index("ux_agents_scheme_identifier", table_name="agents")
    with op.batch_alter_table("agents") as batch_op:
        batch_op.drop_column("scheme_metadata")
        batch_op.drop_column("identifier")
        batch_op.drop_column("scheme")
