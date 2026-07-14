"""Collapse the ERC-8004 agent model into publishers + identities.

Revision ID: 014_agent_to_publisher
Revises: 013_api_key_scope
Create Date: 2026-05-28 00:00:00.000000

Replaces the `agents` table (an ERC-8004 agent indexer artifact) with a
publisher model: a listing is owned by a publisher, and a publisher is
identified by one or more signing identities.

  publishers   publisher_id (PK), storefront_url, created_at, updated_at
  identities   id, publisher_id (FK), scheme, identifier  [unique (scheme, identifier)]
  listings     ... publisher_id (FK)  (drops agent_id, seller, buyer)

`init_db()` builds fresh databases from the models, so a clean checkout
gets the three-table shape directly and this migration is a no-op on it
(the guards below short-circuit). It does real work only when transforming
an existing alembic-managed database: each agent with a usable identity
becomes a publisher + eip191 identity, its listings are repointed, and the
agents / agent_metadata / health_checks tables are dropped.

The collapse is lossy (ERC-8004 agent cards, health, on-chain ids have no
target), so downgrade is not supported.
"""

import sqlalchemy as sa
from alembic import op


revision = "014_agent_to_publisher"
down_revision = "013_api_key_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "publishers" not in tables:
        op.create_table(
            "publishers",
            sa.Column("publisher_id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("storefront_url", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    if "identities" not in tables:
        op.create_table(
            "identities",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("publisher_id", sa.Integer, sa.ForeignKey("publishers.publisher_id", ondelete="CASCADE"), nullable=False),
            sa.Column("scheme", sa.String, nullable=False),
            sa.Column("identifier", sa.String, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ux_identities_scheme_identifier", "identities", ["scheme", "identifier"], unique=True)
        op.create_index("idx_identities_publisher_id", "identities", ["publisher_id"])

    if "listings" not in tables:
        # Fresh DB built by create_all already has the target listings shape.
        return

    listing_cols = {c["name"] for c in insp.get_columns("listings")}
    if "publisher_id" not in listing_cols:
        with op.batch_alter_table("listings") as batch_op:
            batch_op.add_column(sa.Column("publisher_id", sa.Integer, nullable=True))

    # Backfill publishers + identities from the agents table, repointing listings.
    # Real Table constructs (with the PK declared) so inserted_primary_key
    # populates on both sqlite (lastrowid) and postgres (RETURNING).
    meta = sa.MetaData()
    pubs = sa.Table(
        "publishers", meta,
        sa.Column("publisher_id", sa.Integer, primary_key=True),
        sa.Column("storefront_url", sa.Text),
    )
    idents = sa.Table(
        "identities", meta,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("publisher_id", sa.Integer),
        sa.Column("scheme", sa.String),
        sa.Column("identifier", sa.String),
    )
    if "agents" in tables:
        agents = bind.execute(
            sa.text("SELECT agent_id, scheme, identifier, owner, token_uri FROM agents")
        ).fetchall()
        for agent_id, scheme, identifier, owner, token_uri in agents:
            s = scheme or ("eip191" if owner else None)
            i = identifier or (owner.lower() if owner else None)
            if not s or not i:
                continue  # identity-less legacy row — its listings are dropped below
            existing = bind.execute(
                sa.text("SELECT publisher_id FROM identities WHERE scheme = :s AND identifier = :i"),
                {"s": s, "i": i},
            ).scalar()
            if existing is not None:
                pub_id = existing
            else:
                seller = bind.execute(
                    sa.text(
                        "SELECT seller FROM listings WHERE agent_id = :a "
                        "AND seller IS NOT NULL AND seller != '' LIMIT 1"
                    ),
                    {"a": agent_id},
                ).scalar()
                pub_id = bind.execute(
                    pubs.insert().values(storefront_url=seller or token_uri)
                ).inserted_primary_key[0]
                bind.execute(idents.insert().values(publisher_id=pub_id, scheme=s, identifier=i))
            bind.execute(
                sa.text("UPDATE listings SET publisher_id = :p WHERE agent_id = :a"),
                {"p": pub_id, "a": agent_id},
            )

    # Listings whose agent had no usable identity cannot be owned — drop them.
    bind.execute(sa.text("DELETE FROM listings WHERE publisher_id IS NULL"))

    # Drop indexes on the agent-era columns before the batch rebuild, so the
    # rebuilt table does not try to recreate an index over a dropped column.
    existing_idx = {ix["name"] for ix in insp.get_indexes("listings")}
    if "idx_listings_agent_id" in existing_idx:
        op.drop_index("idx_listings_agent_id", table_name="listings")

    # Rebuild listings against the publisher FK; drop the agent-era columns.
    with op.batch_alter_table("listings") as batch_op:
        for col in ("agent_id", "seller", "buyer"):
            if col in listing_cols:
                batch_op.drop_column(col)
        batch_op.alter_column("publisher_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_index("idx_listings_publisher_id", ["publisher_id"])
        batch_op.create_foreign_key(
            "fk_listings_publisher", "publishers", ["publisher_id"], ["publisher_id"], ondelete="CASCADE"
        )

    # Drop the legacy tables, dependents first.
    for t in ("agent_metadata", "health_checks", "agents"):
        if t in tables:
            op.drop_table(t)


def downgrade() -> None:
    raise NotImplementedError(
        "014 collapses the agent model into publishers/identities and is not "
        "reversible (ERC-8004 agent data has no target in the new schema)."
    )
