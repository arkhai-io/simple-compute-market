"""The accepted negotiation's policy scalar, stored as ``negotiated_scalar``.

A real SQLite database migrated through core's chain; a thread recorded before
the column carries its name keeps its exact value under it.
"""

from __future__ import annotations

import dataclasses
import sqlite3

from market_identity import Ed25519Signer
from market_schema_migrations import SqliteMigrationConnection, migrate

from core_database import CORE_CHAIN
from core_storefront.sqlite_client import SQLiteClient

#: Development keys, never used on a public network.
_BUYER = Ed25519Signer(b"\x61" * 32).identity
_SELLER = Ed25519Signer(b"\x62" * 32).identity


async def test_a_recorded_thread_keeps_its_scalar_under_the_column_name(tmp_path) -> None:
    path = tmp_path / "upgraded.db"
    scalar = 150 * 10**18
    connection = sqlite3.connect(path)
    try:
        before = dataclasses.replace(
            CORE_CHAIN,
            migrations=tuple(
                migration for migration in CORE_CHAIN.migrations
                if migration.id != "20261111_002_negotiation_negotiated_scalar"
            ),
        )
        migrate(before, SqliteMigrationConnection(connection))
        with connection:
            connection.execute(
                "INSERT INTO negotiation_threads (negotiation_id, our_listing_id, "
                "buyer_scheme, buyer_identifier, seller_scheme, seller_identifier, "
                "terminal_state, agreed_price) VALUES ('neg-1', 'L1', ?, ?, ?, ?, "
                "'success', ?)",
                (
                    _BUYER.scheme.value, _BUYER.identifier,
                    _SELLER.scheme.value, _SELLER.identifier,
                    str(scalar),
                ),
            )
        migrate(CORE_CHAIN, SqliteMigrationConnection(connection))
    finally:
        connection.close()

    thread = await SQLiteClient(str(path)).load_negotiation_thread_row(
        negotiation_id="neg-1"
    )
    assert thread is not None
    assert "agreed_price" not in thread
    assert thread["negotiated_scalar"] == scalar
