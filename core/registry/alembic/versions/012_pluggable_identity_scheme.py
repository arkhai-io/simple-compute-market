"""agents: scheme-tagged identity columns + backfill (phase 3/4 of pluggable identity).

Revision ID: 012_pluggable_identity_scheme
Revises: 011_listing_accepted_escrows
Create Date: 2026-05-27 00:00:00.000000

Adds ``scheme`` + ``identifier`` + ``scheme_metadata`` to the ``agents``
table. Existing rows with a known wallet ``owner`` are migrated to the
``eip191`` scheme with the lowercased owner as the identifier; their
ERC-8004 components (canonical ``agent_id``, ``chain_id``,
``onchain_agent_id``, ``identity_registry``, ``token_uri``) are
captured in ``scheme_metadata`` for transparency during the transition
window. Owner-less rows (residue from the legacy chain-walk indexer)
stay with NULL scheme/identifier and are left for Phase 4 cleanup.

If two existing rows share the same ``owner.lower()``, neither is
backfilled — the operator picks the canonical row before Phase 4.
This matches the design's "one Agent per signer identity" invariant
without forcing a destructive choice during the migration.

The legacy ``agent_id`` + ``chain_id`` + ``identity_registry`` +
``onchain_agent_id`` + ``token_uri`` columns are untouched here so the
existing URL form ``/agents/{eip155:...}/listings`` keeps resolving;
Phase 4 drops them once the ERC-8004 scheme is removed entirely.
"""

import json

import sqlalchemy as sa
from alembic import op


revision = "012_pluggable_identity_scheme"
down_revision = "011_listing_accepted_escrows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add the new columns — nullable initially so existing rows survive.
    with op.batch_alter_table("agents") as batch_op:
        batch_op.add_column(sa.Column("scheme", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("identifier", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("scheme_metadata", sa.JSON(), nullable=True))

    # 2. Backfill: tag each unique-owner row with (eip191, owner.lower()).
    #    Rows whose owner is NULL or whose lowercased owner collides with
    #    another row stay with NULL scheme/identifier (Phase 4 cleanup).
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, agent_id, chain_id, identity_registry, "
            "onchain_agent_id, owner, token_uri FROM agents"
        )
    ).fetchall()

    # Group by lowered owner so we can detect collisions.
    by_owner: dict[str, list] = {}
    for row in rows:
        owner = (row[5] or "").lower()
        if not owner:
            continue
        by_owner.setdefault(owner, []).append(row)

    for owner, group in by_owner.items():
        if len(group) > 1:
            # Collision — skip this group; Phase 4 cleanup handles it.
            continue
        (row_id, agent_id, chain_id, identity_registry,
         onchain_agent_id, _, token_uri) = group[0]
        metadata = {
            "agent_id": agent_id,
            "chain_id": chain_id,
            "identity_registry": identity_registry,
            "onchain_agent_id": onchain_agent_id,
            "token_uri": token_uri,
        }
        # Drop keys with NULL value so the JSON stays minimal.
        metadata = {k: v for k, v in metadata.items() if v is not None}
        conn.execute(
            sa.text(
                "UPDATE agents SET scheme = :scheme, identifier = :identifier, "
                "scheme_metadata = :sm WHERE id = :id"
            ),
            {
                "scheme": "eip191",
                "identifier": owner,
                "sm": json.dumps(metadata) if metadata else None,
                "id": row_id,
            },
        )

    # 3. Enforce uniqueness on (scheme, identifier) — NULL-safe in both
    #    SQLite and Postgres (NULLs DISTINCT by default), so legacy rows
    #    with NULL fields don't collide with each other.
    op.create_index(
        "ux_agents_scheme_identifier",
        "agents",
        ["scheme", "identifier"],
        unique=True,
    )
    op.create_index(
        "idx_agents_scheme",
        "agents",
        ["scheme"],
    )


def downgrade() -> None:
    op.drop_index("idx_agents_scheme", table_name="agents")
    op.drop_index("ux_agents_scheme_identifier", table_name="agents")
    with op.batch_alter_table("agents") as batch_op:
        batch_op.drop_column("scheme_metadata")
        batch_op.drop_column("identifier")
        batch_op.drop_column("scheme")
