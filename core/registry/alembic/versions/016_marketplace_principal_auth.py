"""Add strict publisher-principal lifecycle and request replay state.

Revision ID: 016_marketplace_principal_auth
Revises: 015_listing_settlement_options
"""

from __future__ import annotations

import base64
import binascii
import re

import sqlalchemy as sa
from alembic import op

revision = "016_marketplace_principal_auth"
down_revision = "015_listing_settlement_options"
branch_labels = None
depends_on = None

_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]{43}$")


def _canonical_principal(scheme: object, identifier: object) -> tuple[str, str]:
    if scheme == "eip191" and isinstance(identifier, str) and _ADDRESS.fullmatch(identifier):
        return "eip191", identifier.lower()
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
        if len(raw) == 32 and canonical == identifier:
            return "ed25519", identifier
    raise RuntimeError("unknown or malformed publisher principal")


def _validate_population(bind) -> list[tuple[int, str]]:
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    required = {"publishers", "identities", "listings"}
    if not required.issubset(tables):
        missing = ", ".join(sorted(required - tables))
        raise RuntimeError(f"registry principal migration is missing tables: {missing}")

    publishers = {
        int(row[0])
        for row in bind.execute(sa.text("SELECT publisher_id FROM publishers"))
    }
    rows = bind.execute(
        sa.text(
            "SELECT id, publisher_id, scheme, identifier FROM identities ORDER BY id"
        )
    ).fetchall()
    canonical_updates: list[tuple[int, str]] = []
    principals: dict[tuple[str, str], int] = {}
    identities_per_publisher: dict[int, int] = {publisher_id: 0 for publisher_id in publishers}
    for identity_id, publisher_id, scheme, identifier in rows:
        if publisher_id not in publishers:
            raise RuntimeError("publisher identity references a missing publisher")
        canonical_scheme, canonical_identifier = _canonical_principal(scheme, identifier)
        principal = (canonical_scheme, canonical_identifier)
        if principal in principals:
            raise RuntimeError("duplicate canonical publisher principal")
        principals[principal] = int(identity_id)
        identities_per_publisher[int(publisher_id)] += 1
        if canonical_identifier != identifier:
            canonical_updates.append((int(identity_id), canonical_identifier))

    if any(count != 1 for count in identities_per_publisher.values()):
        raise RuntimeError("publisher population has missing or duplicate active bindings")

    listing_publishers = bind.execute(
        sa.text("SELECT listing_id, publisher_id FROM listings")
    ).fetchall()
    for _listing_id, publisher_id in listing_publishers:
        if publisher_id not in publishers:
            raise RuntimeError("listing references a missing publisher")
    return canonical_updates


def upgrade() -> None:
    bind = op.get_bind()
    canonical_updates = _validate_population(bind)
    for identity_id, identifier in canonical_updates:
        bind.execute(
            sa.text("UPDATE identities SET identifier = :identifier WHERE id = :id"),
            {"identifier": identifier, "id": identity_id},
        )

    inspector = sa.inspect(bind)
    identity_columns = {column["name"] for column in inspector.get_columns("identities")}
    with op.batch_alter_table("identities") as batch_op:
        if "status" not in identity_columns:
            batch_op.add_column(
                sa.Column(
                    "status",
                    sa.String(),
                    nullable=False,
                    server_default="primary",
                )
            )
        if "active_until" not in identity_columns:
            batch_op.add_column(sa.Column("active_until", sa.DateTime(timezone=True)))
        if "retired_at" not in identity_columns:
            batch_op.add_column(sa.Column("retired_at", sa.DateTime(timezone=True)))
        if "disabled_at" not in identity_columns:
            batch_op.add_column(sa.Column("disabled_at", sa.DateTime(timezone=True)))

    op.create_index(
        "ux_identities_one_primary_per_publisher",
        "identities",
        ["publisher_id"],
        unique=True,
        sqlite_where=sa.text("status = 'primary'"),
        postgresql_where=sa.text("status = 'primary'"),
    )

    tables = set(sa.inspect(bind).get_table_names())
    if "publisher_replay_reservations" not in tables:
        op.create_table(
            "publisher_replay_reservations",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("principal_scheme", sa.String(), nullable=False),
            sa.Column("principal_identifier", sa.String(), nullable=False),
            sa.Column("request_id", sa.String(), nullable=False),
            sa.Column("request_hash", sa.String(), nullable=False),
            sa.Column("response_status", sa.Integer()),
            sa.Column("response_body", sa.JSON()),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("completed_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint(
                "principal_scheme",
                "principal_identifier",
                "request_id",
                name="uq_publisher_replay_principal_request",
            ),
        )
        op.create_index(
            "idx_publisher_replay_created_at",
            "publisher_replay_reservations",
            ["created_at"],
        )

    if "publisher_identity_rotations" not in tables:
        op.create_table(
            "publisher_identity_rotations",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "publisher_id",
                sa.Integer(),
                sa.ForeignKey("publishers.publisher_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("nonce", sa.String(), nullable=False),
            sa.Column("intent_hash", sa.String(), nullable=False),
            sa.Column("current_scheme", sa.String(), nullable=False),
            sa.Column("current_identifier", sa.String(), nullable=False),
            sa.Column("replacement_scheme", sa.String(), nullable=False),
            sa.Column("replacement_identifier", sa.String(), nullable=False),
            sa.Column("overlap_seconds", sa.Integer(), nullable=False),
            sa.Column("expires_at", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column(
                "applied_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("retire_at", sa.DateTime(timezone=True)),
            sa.Column("retired_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint(
                "publisher_id",
                "nonce",
                name="uq_publisher_rotation_nonce",
            ),
        )
        op.create_index(
            "idx_publisher_rotations_publisher_id",
            "publisher_identity_rotations",
            ["publisher_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "publisher_identity_rotations" in tables:
        op.drop_index(
            "idx_publisher_rotations_publisher_id",
            table_name="publisher_identity_rotations",
        )
        op.drop_table("publisher_identity_rotations")
    if "publisher_replay_reservations" in tables:
        op.drop_index(
            "idx_publisher_replay_created_at",
            table_name="publisher_replay_reservations",
        )
        op.drop_table("publisher_replay_reservations")
    identity_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("identities")
    }
    if "ux_identities_one_primary_per_publisher" in identity_indexes:
        op.drop_index(
            "ux_identities_one_primary_per_publisher",
            table_name="identities",
        )

    columns = {column["name"] for column in sa.inspect(bind).get_columns("identities")}
    with op.batch_alter_table("identities") as batch_op:
        for name in ("disabled_at", "retired_at", "active_until", "status"):
            if name in columns:
                batch_op.drop_column(name)
