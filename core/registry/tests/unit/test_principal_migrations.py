"""Focused registry principal migration coverage."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

_MIGRATIONS = Path(__file__).parents[2] / "alembic" / "versions"


def _load(name: str):
    path = _MIGRATIONS / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _operations(connection) -> Operations:
    return Operations(MigrationContext.configure(connection))


def _pre_principal_schema(connection) -> None:
    connection.execute(
        sa.text(
            "CREATE TABLE publishers ("
            "publisher_id INTEGER PRIMARY KEY, storefront_url TEXT, "
            "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
        )
    )
    connection.execute(
        sa.text(
            "CREATE TABLE identities ("
            "id INTEGER PRIMARY KEY, publisher_id INTEGER NOT NULL, "
            "scheme VARCHAR NOT NULL, identifier VARCHAR NOT NULL, "
            "created_at DATETIME NOT NULL)"
        )
    )
    connection.execute(
        sa.text(
            "CREATE TABLE listings (listing_id VARCHAR PRIMARY KEY, "
            "publisher_id INTEGER NOT NULL)"
        )
    )


def test_valid_legacy_address_normalizes_without_changing_stable_ids() -> None:
    module = _load("016_marketplace_principal_auth.py")
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _pre_principal_schema(connection)
        connection.execute(
            sa.text(
                "INSERT INTO publishers VALUES "
                "(41, 'https://seller', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO identities VALUES "
                "(7, 41, 'eip191', '0xABCDEF0000000000000000000000000000000001', "
                "CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            sa.text("INSERT INTO listings VALUES ('stable-listing', 41)")
        )
        with patch.object(module, "op", _operations(connection)):
            module.upgrade()

        principal = connection.execute(
            sa.text("SELECT scheme, identifier, publisher_id FROM identities")
        ).one()
        listing = connection.execute(
            sa.text("SELECT listing_id, publisher_id FROM listings")
        ).one()
        assert principal == (
            "eip191",
            "0xabcdef0000000000000000000000000000000001",
            41,
        )
        assert listing == ("stable-listing", 41)


def test_duplicate_normalized_owners_abort_before_schema_change() -> None:
    module = _load("016_marketplace_principal_auth.py")
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _pre_principal_schema(connection)
        connection.execute(
            sa.text(
                "INSERT INTO publishers VALUES "
                "(1, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "(2, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO identities VALUES "
                "(1, 1, 'eip191', '0xABCDEF0000000000000000000000000000000001', CURRENT_TIMESTAMP), "
                "(2, 2, 'eip191', '0xabcdef0000000000000000000000000000000001', CURRENT_TIMESTAMP)"
            )
        )
        with patch.object(module, "op", _operations(connection)):
            with pytest.raises(RuntimeError, match="duplicate canonical"):
                module.upgrade()
        columns = {
            column["name"]
            for column in sa.inspect(connection).get_columns("identities")
        }
        assert "status" not in columns


@pytest.mark.parametrize(
    "scheme, identifier",
    [
        ("eip191", "not-an-address"),
        ("unknown", "0x" + "11" * 20),
        ("ed25519", "short"),
    ],
)
def test_malformed_or_unknown_population_fails_closed(
    scheme: str,
    identifier: str,
) -> None:
    module = _load("016_marketplace_principal_auth.py")
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _pre_principal_schema(connection)
        connection.execute(
            sa.text(
                "INSERT INTO publishers VALUES "
                "(1, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO identities VALUES "
                "(1, 1, :scheme, :identifier, CURRENT_TIMESTAMP)"
            ),
            {"scheme": scheme, "identifier": identifier},
        )
        with patch.object(module, "op", _operations(connection)):
            with pytest.raises(RuntimeError, match="unknown or malformed"):
                module.upgrade()


def test_referential_gap_aborts_migration() -> None:
    module = _load("016_marketplace_principal_auth.py")
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _pre_principal_schema(connection)
        connection.execute(
            sa.text("INSERT INTO listings VALUES ('orphan', 99)")
        )
        with patch.object(module, "op", _operations(connection)):
            with pytest.raises(RuntimeError, match="missing publisher"):
                module.upgrade()


def test_address_owned_listing_converts_to_explicit_principal_atomically() -> None:
    module = _load("014_agent_to_publisher.py")
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE agents ("
                "id INTEGER, agent_id VARCHAR PRIMARY KEY, scheme VARCHAR, "
                "identifier VARCHAR, owner VARCHAR, token_uri TEXT)"
            )
        )
        connection.execute(
            sa.text(
                "CREATE TABLE listings (listing_id VARCHAR PRIMARY KEY, "
                "agent_id VARCHAR NOT NULL, seller TEXT, buyer TEXT)"
            )
        )
        connection.execute(
            sa.text("CREATE INDEX idx_listings_agent_id ON listings (agent_id)")
        )
        connection.execute(
            sa.text(
                "INSERT INTO agents VALUES "
                "(17, 'legacy-agent', NULL, NULL, "
                "'0xABCDEF0000000000000000000000000000000001', NULL)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO listings VALUES "
                "('legacy-listing', 'legacy-agent', 'https://seller', NULL)"
            )
        )
        with patch.object(module, "op", _operations(connection)):
            module.upgrade()

        principal = connection.execute(
            sa.text("SELECT publisher_id, scheme, identifier FROM identities")
        ).one()
        listing = connection.execute(
            sa.text("SELECT listing_id, publisher_id FROM listings")
        ).one()
        assert principal == (
            17,
            "eip191",
            "0xabcdef0000000000000000000000000000000001",
        )
        assert listing == ("legacy-listing", 17)
        assert "agents" not in sa.inspect(connection).get_table_names()


def test_lifecycle_migration_downgrade_removes_owned_state() -> None:
    module = _load("016_marketplace_principal_auth.py")
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _pre_principal_schema(connection)
        operations = _operations(connection)
        with patch.object(module, "op", operations):
            module.upgrade()
            module.downgrade()
        tables = set(sa.inspect(connection).get_table_names())
        columns = {
            column["name"]
            for column in sa.inspect(connection).get_columns("identities")
        }
        assert "publisher_replay_reservations" not in tables
        assert "publisher_identity_rotations" not in tables
        assert "status" not in columns

def test_replay_lease_migration_restarts_incomplete_attempts() -> None:
    module = _load("017_publisher_replay_leases.py")
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE publisher_replay_reservations ("
                "id INTEGER PRIMARY KEY, principal_scheme VARCHAR NOT NULL, "
                "principal_identifier VARCHAR NOT NULL, request_id VARCHAR NOT NULL, "
                "request_hash VARCHAR NOT NULL, response_status INTEGER, "
                "response_body JSON, created_at DATETIME NOT NULL, completed_at DATETIME)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO publisher_replay_reservations "
                "(id, principal_scheme, principal_identifier, request_id, "
                "request_hash, created_at, completed_at) VALUES "
                "(1, 'ed25519', 'owner', 'pending', 'hash', "
                "'2026-01-01 00:00:00', NULL), "
                "(2, 'ed25519', 'owner', 'done', 'hash', "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:01')"
            )
        )
        operations = _operations(connection)
        with patch.object(module, "op", operations):
            module.upgrade()
        rows = connection.execute(
            sa.text(
                "SELECT id, lease_owner, lease_expires_at "
                "FROM publisher_replay_reservations ORDER BY id"
            )
        ).all()
        assert rows[0][1] is None
        assert rows[0][2] is not None
        assert rows[1][1:] == (None, None)
