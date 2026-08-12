"""Atomically convert legacy address-owned agents into stable publishers.

Revision ID: 014_agent_to_publisher
Revises: 013_api_key_scope
"""

from __future__ import annotations

import base64
import binascii
import re

import sqlalchemy as sa
from alembic import op

revision = "014_agent_to_publisher"
down_revision = "013_api_key_scope"
branch_labels = None
depends_on = None

_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]{43}$")


def _principal(scheme: object, identifier: object, owner: object) -> tuple[str, str]:
    if scheme is None and identifier is None:
        scheme = "eip191"
        identifier = owner
    elif scheme is None or identifier is None:
        raise RuntimeError("partially populated legacy publisher principal")

    if scheme == "eip191" and isinstance(identifier, str) and _ADDRESS.fullmatch(identifier):
        normalized = identifier.lower()
        if owner is not None:
            if not isinstance(owner, str) or not _ADDRESS.fullmatch(owner):
                raise RuntimeError("malformed legacy publisher owner address")
            if owner.lower() != normalized:
                raise RuntimeError("legacy owner and principal identifier disagree")
        return "eip191", normalized

    if scheme == "ed25519" and isinstance(identifier, str) and _BASE64URL.fullmatch(identifier):
        try:
            raw = base64.b64decode(
                identifier + "=" * (-len(identifier) % 4),
                altchars=b"-_",
                validate=True,
            )
        except (binascii.Error, ValueError) as exc:
            raise RuntimeError("malformed ed25519 publisher principal") from exc
        canonical = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
        if len(raw) == 32 and canonical == identifier and owner is None:
            return "ed25519", identifier

    raise RuntimeError("unknown or malformed legacy publisher principal")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "publishers" not in tables:
        op.create_table(
            "publishers",
            sa.Column("publisher_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("storefront_url", sa.Text()),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
    if "identities" not in tables:
        op.create_table(
            "identities",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "publisher_id",
                sa.Integer(),
                sa.ForeignKey("publishers.publisher_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("scheme", sa.String(), nullable=False),
            sa.Column("identifier", sa.String(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "ux_identities_scheme_identifier",
            "identities",
            ["scheme", "identifier"],
            unique=True,
        )
        op.create_index(
            "idx_identities_publisher_id",
            "identities",
            ["publisher_id"],
        )

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "listings" not in tables:
        raise RuntimeError("legacy registry migration is missing listings")

    listing_columns = {column["name"] for column in inspector.get_columns("listings")}
    if "publisher_id" in listing_columns and "agent_id" not in listing_columns:
        if "agents" in tables:
            raise RuntimeError("partially migrated legacy publisher tables detected")
        return
    if "agents" not in tables or "agent_id" not in listing_columns:
        raise RuntimeError("legacy listing ownership is referentially incomplete")
    if bind.execute(sa.text("SELECT COUNT(*) FROM identities")).scalar_one():
        raise RuntimeError("partially migrated publisher identities detected")
    if bind.execute(sa.text("SELECT COUNT(*) FROM publishers")).scalar_one():
        raise RuntimeError("partially migrated publishers detected")

    agent_rows = bind.execute(
        sa.text(
            "SELECT id, agent_id, scheme, identifier, owner, token_uri "
            "FROM agents ORDER BY agent_id"
        )
    ).fetchall()
    agents: dict[str, tuple[int | None, str, str, str | None]] = {}
    principals: set[tuple[str, str]] = set()
    usable_legacy_ids: set[int] = set()
    for row_id, agent_id, scheme, identifier, owner, token_uri in agent_rows:
        if not isinstance(agent_id, str) or not agent_id or agent_id in agents:
            raise RuntimeError("malformed or duplicate legacy agent identity")
        normalized_scheme, normalized_identifier = _principal(scheme, identifier, owner)
        principal = (normalized_scheme, normalized_identifier)
        if principal in principals:
            raise RuntimeError("duplicate canonical publisher principal")
        principals.add(principal)
        legacy_id = row_id if isinstance(row_id, int) and row_id > 0 else None
        if legacy_id is not None:
            if legacy_id in usable_legacy_ids:
                raise RuntimeError("duplicate legacy publisher id")
            usable_legacy_ids.add(legacy_id)
        agents[agent_id] = (
            legacy_id,
            normalized_scheme,
            normalized_identifier,
            token_uri,
        )

    listing_rows = bind.execute(
        sa.text("SELECT listing_id, agent_id, seller FROM listings")
    ).fetchall()
    storefronts: dict[str, set[str]] = {agent_id: set() for agent_id in agents}
    for _listing_id, agent_id, seller in listing_rows:
        if agent_id not in agents:
            raise RuntimeError("listing references a missing legacy publisher")
        if seller:
            storefronts[agent_id].add(str(seller))
    if any(len(values) > 1 for values in storefronts.values()):
        raise RuntimeError("legacy publisher has conflicting storefront ownership")

    if "publisher_id" not in listing_columns:
        with op.batch_alter_table("listings") as batch_op:
            batch_op.add_column(sa.Column("publisher_id", sa.Integer(), nullable=True))

    metadata = sa.MetaData()
    publishers = sa.Table(
        "publishers",
        metadata,
        sa.Column("publisher_id", sa.Integer(), primary_key=True),
        sa.Column("storefront_url", sa.Text()),
    )
    identities = sa.Table(
        "identities",
        metadata,
        sa.Column("publisher_id", sa.Integer()),
        sa.Column("scheme", sa.String()),
        sa.Column("identifier", sa.String()),
    )
    for agent_id, (legacy_id, scheme, identifier, token_uri) in agents.items():
        storefront_values = storefronts[agent_id]
        storefront_url = next(iter(storefront_values), None) or token_uri
        values = {"storefront_url": storefront_url}
        if legacy_id is not None:
            values["publisher_id"] = legacy_id
        inserted = bind.execute(publishers.insert().values(**values))
        publisher_id = legacy_id or inserted.inserted_primary_key[0]
        bind.execute(
            identities.insert().values(
                publisher_id=publisher_id,
                scheme=scheme,
                identifier=identifier,
            )
        )
        bind.execute(
            sa.text("UPDATE listings SET publisher_id = :publisher_id WHERE agent_id = :agent_id"),
            {"publisher_id": publisher_id, "agent_id": agent_id},
        )

    if bind.execute(
        sa.text("SELECT COUNT(*) FROM listings WHERE publisher_id IS NULL")
    ).scalar_one():
        raise RuntimeError("listing owner conversion left unbound rows")

    existing_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("listings")
    }
    if "idx_listings_agent_id" in existing_indexes:
        op.drop_index("idx_listings_agent_id", table_name="listings")

    with op.batch_alter_table("listings") as batch_op:
        for column in ("agent_id", "seller", "buyer"):
            if column in listing_columns:
                batch_op.drop_column(column)
        batch_op.alter_column(
            "publisher_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_index("idx_listings_publisher_id", ["publisher_id"])
        batch_op.create_foreign_key(
            "fk_listings_publisher",
            "publishers",
            ["publisher_id"],
            ["publisher_id"],
            ondelete="CASCADE",
        )

    for table in ("agent_metadata", "health_checks", "agents"):
        if table in tables:
            op.drop_table(table)


def downgrade() -> None:
    raise NotImplementedError(
        "publisher conversion cannot reconstruct retired ERC-8004 agent metadata"
    )
