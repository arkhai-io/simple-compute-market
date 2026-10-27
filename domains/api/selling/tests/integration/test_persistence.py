"""The storefront's persistence under a neutral bundle: its tables, its terms, and the one-transaction opening."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest
from market_resource_pools import ResolvedPool
from market_resource_pools_contracts.backing import BACKED

from arkhai_api_selling.persistence import (
    ESCROW_SETTLEMENT_IDENTITY_MIGRATION,
    ISSUANCE_EVIDENCE_MIGRATION,
    TERMS_TABLE,
    StorefrontSQLiteClient,
    migrations,
)
from arkhai_api_selling.quota_listing import QuotaPool, prepare_listing_binding
from tests.bundles import BUYER, CLAIMANT, DOMAIN, EXAMPLE

RESOURCE = {"product": "alpha", "quota": "quota-a", "offering_mode": "example"}


def _client(tmp_path) -> StorefrontSQLiteClient:
    return StorefrontSQLiteClient(str(tmp_path / "storefront.db"), EXAMPLE)


async def _bound_listing(client: StorefrontSQLiteClient, listing_id: str = "L-1") -> None:
    binding = prepare_listing_binding(
        EXAMPLE,
        listing_id=listing_id,
        site_id="quota",
        listing_resource=RESOURCE,
        pool=QuotaPool("default", ResolvedPool(BACKED, frozenset({"example"}), True)),
        domain=DOMAIN,
    )
    now = datetime.now(UTC).isoformat()
    await client.upsert_listing_with_binding(
        binding=binding,
        status="open",
        created_at=now,
        updated_at=now,
        listing_resource=RESOURCE,
        fulfillment_resource=None,
        max_duration_seconds=None,
        storefront_url="https://seller.example",
        seller_principal=CLAIMANT,
    )


def _tables(client: StorefrontSQLiteClient) -> set[str]:
    with sqlite3.connect(client.db_path) as conn:
        return {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }


def _applied(client: StorefrontSQLiteClient) -> set[str]:
    with sqlite3.connect(client.db_path) as conn:
        return {str(value) for row in conn.execute("SELECT * FROM schema_migrations") for value in row}


def test_the_tables_are_named_from_the_prefix_and_the_migrations_keep_their_identifiers(tmp_path):
    client = _client(tmp_path)

    tables = _tables(client)
    assert {
        "example_settlement_evidence",
        "example_issuance_progress",
        "example_issuance_evidence",
        "example_private_results",
        TERMS_TABLE,
    } <= tables
    assert not any(table.startswith("api_credit") for table in tables)
    assert [migration.id for migration in migrations(EXAMPLE)] == [
        ESCROW_SETTLEMENT_IDENTITY_MIGRATION,
        ISSUANCE_EVIDENCE_MIGRATION,
    ]
    assert {ESCROW_SETTLEMENT_IDENTITY_MIGRATION, ISSUANCE_EVIDENCE_MIGRATION} <= _applied(client)
    with sqlite3.connect(client.db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(escrows)")}
    assert {"obligation_ref", "obligation_index"} <= columns


async def test_credit_terms_round_trip_and_are_replaced_whole(tmp_path):
    client = _client(tmp_path)

    await client.save_credit_terms(negotiation_id="neg-1", quantity=3, key_mode="new")
    assert await client.load_credit_terms(negotiation_id="neg-1") == {
        "negotiation_id": "neg-1", "quantity": 3, "key_mode": "new", "key_id": None,
    }
    await client.save_credit_terms(negotiation_id="neg-1", quantity=5, key_mode="existing", key_id="ak_1")
    assert await client.load_credit_terms(negotiation_id="neg-1") == {
        "negotiation_id": "neg-1", "quantity": 5, "key_mode": "existing", "key_id": "ak_1",
    }
    assert await client.load_credit_terms(negotiation_id="neg-2") is None


async def test_a_listing_without_a_binding_refuses_the_database_naming_the_noun(tmp_path):
    client = _client(tmp_path)
    now = datetime.now(UTC).isoformat()
    await client.upsert_listing(
        listing_id="L-unbound",
        status="open",
        created_at=now,
        updated_at=now,
        listing_resource=RESOURCE,
        fulfillment_resource=None,
        max_duration_seconds=None,
        storefront_url="https://seller.example",
        seller_principal=CLAIMANT,
    )

    with pytest.raises(RuntimeError, match=r"^credit listing 'L-unbound' has no durable listing binding"):
        _client(tmp_path)


def _opening(negotiation_id: str = "neg-1") -> tuple[dict, dict]:
    thread = {
        "negotiation_id": negotiation_id,
        "our_listing_id": "L-1",
        "their_listing_id": "",
        "our_agent_id": "https://seller.example",
        "their_agent_id": "https://buyer.example",
        "buyer_principal": BUYER,
        "seller_principal": CLAIMANT,
        "owner_id": "https://seller.example",
        "our_initial_price": 300,
        "our_strategy": "maximize",
        "provision_terms": {"kind": EXAMPLE.kind, "version": 1, "payload": {"quantity": 3, "key": {"mode": "new"}}},
    }
    message = {
        "negotiation_id": negotiation_id,
        "round": None,
        "sender_principal": BUYER,
        "sender_role": "buyer",
        "our_price": 300,
        "their_price": 250,
        "proposed_price": 250,
        "action_taken": "make_offer",
        "message_type": "offer",
        "timestamp": "2026-01-01T00:00:00+00:00",
    }
    return thread, message


def _counts(client: StorefrontSQLiteClient) -> dict[str, int]:
    with sqlite3.connect(client.db_path) as conn:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("negotiation_threads", "negotiation_messages", TERMS_TABLE)
        }


async def test_an_opening_records_the_thread_its_message_its_binding_and_its_terms_together(tmp_path):
    from arkhai_api_selling.persistence import write_credit_terms

    client = _client(tmp_path)
    await _bound_listing(client)
    thread, message = _opening()

    await client.open_negotiation(
        thread=thread,
        message=message,
        domain_writes=lambda conn: write_credit_terms(
            conn, negotiation_id="neg-1", quantity=3, key_mode="new"
        ),
    )

    assert _counts(client) == {"negotiation_threads": 1, "negotiation_messages": 1, TERMS_TABLE: 1}
    bound = await client.load_thread_binding(negotiation_id="neg-1")
    listing = await client.load_listing_binding(listing_id="L-1")
    assert (bound.listing_id, bound.site_id, bound.binding) == ("L-1", listing.site_id, listing.binding)
    assert (await client.load_credit_terms(negotiation_id="neg-1"))["quantity"] == 3


async def test_a_failing_terms_write_leaves_no_thread_message_binding_or_terms(tmp_path):
    client = _client(tmp_path)
    await _bound_listing(client)
    thread, message = _opening()

    def failing_terms(conn: sqlite3.Connection) -> None:
        conn.execute(
            f"INSERT INTO {TERMS_TABLE}(negotiation_id, quantity, key_mode) VALUES (?, ?, ?)",
            ("neg-1", 3, "new"),
        )
        raise sqlite3.OperationalError("the terms write failed")

    with pytest.raises(sqlite3.OperationalError):
        await client.open_negotiation(thread=thread, message=message, domain_writes=failing_terms)

    assert _counts(client) == {"negotiation_threads": 0, "negotiation_messages": 0, TERMS_TABLE: 0}
    assert await client.load_negotiation_thread_row(negotiation_id="neg-1") is None
    with pytest.raises(KeyError):
        await client.load_thread_binding(negotiation_id="neg-1")
