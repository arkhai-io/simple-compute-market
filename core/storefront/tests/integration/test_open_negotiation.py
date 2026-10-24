"""An opening is one transaction: the thread, its first message, its listing's binding, and the domain's writes."""

from __future__ import annotations

import base64
import sqlite3
from datetime import UTC, datetime

import pytest
from market_core import DomainIdentity
from market_identity import Identity, IdentityScheme

from core_storefront.domain_registry import (
    StorefrontDomainBinding,
    StorefrontListingBinding,
    build_storefront_derivation_key,
)
from core_storefront.sqlite_client import SQLiteClient


def _principal(byte: int) -> Identity:
    identifier = base64.urlsafe_b64encode(bytes([byte]) * 32).rstrip(b"=").decode()
    return Identity(scheme=IdentityScheme.ED25519, identifier=identifier)


BUYER = _principal(0x11)
SELLER = _principal(0x22)
DOMAIN = StorefrontDomainBinding(
    offering_mode="vm",
    domain_identity=DomainIdentity("compute.v1"),
    contract_major=1,
    contract_minor=0,
)


async def _storefront(tmp_path) -> SQLiteClient:
    client = SQLiteClient(str(tmp_path / "storefront.db"))
    binding = StorefrontListingBinding.from_source_envelope(
        listing_id="listing-a",
        site_id="site-a",
        pool_id="pool-a",
        binding=DOMAIN,
        derivation_key=build_storefront_derivation_key(
            site_id="site-a",
            offering_mode="vm",
            binding=DOMAIN,
            source_identity={"pool_id": "pool-a", "slice": 1},
        ),
        source_envelope={
            "kind": "vm.listing-source.v1",
            "schema_version": 1,
            "payload": {"pool_id": "pool-a", "slice": 1},
        },
        last_reconciled_at=datetime.now(UTC).isoformat(),
        capacity_backing="backed",
    )
    await client.upsert_listing_with_binding(
        binding=binding,
        status="open",
        created_at="2026-08-15T00:00:00Z",
        updated_at="2026-08-15T00:00:00Z",
        listing_resource={"resource_type": "compute.gpu", "offering_mode": "vm"},
        fulfillment_resource=None,
        max_duration_seconds=3600,
        storefront_url="https://seller.example",
        seller_principal=SELLER,
    )
    return client


def _thread(negotiation_id: str = "neg-1") -> dict:
    return {
        "negotiation_id": negotiation_id,
        "our_listing_id": "listing-a",
        "their_listing_id": "",
        "our_agent_id": "https://seller.example",
        "their_agent_id": "https://buyer.example",
        "buyer_principal": BUYER,
        "seller_principal": SELLER,
        "owner_id": "https://seller.example",
        "our_initial_price": 10,
        "our_strategy": "listed_price",
        "provision_terms": {"units": 3},
    }


def _message(negotiation_id: str = "neg-1") -> dict:
    return {
        "negotiation_id": negotiation_id,
        "round": None,
        "sender_principal": BUYER,
        "sender_role": "buyer",
        "our_price": 10,
        "their_price": 9,
        "proposed_price": 9,
        "action_taken": "make_offer",
        "message_type": "offer",
        "timestamp": "2026-08-15T00:00:00+00:00",
    }


def _rows(client: SQLiteClient) -> dict[str, int]:
    with sqlite3.connect(client.db_path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS domain_opening (negotiation_id TEXT PRIMARY KEY)")
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("negotiation_threads", "negotiation_messages", "domain_opening")
        }


@pytest.mark.asyncio
async def test_an_opening_writes_the_thread_its_message_its_binding_and_the_domains_state_together(tmp_path):
    client = await _storefront(tmp_path)
    _rows(client)

    def domain_writes(conn: sqlite3.Connection) -> None:
        conn.execute("INSERT INTO domain_opening (negotiation_id) VALUES (?)", ("neg-1",))

    round_number = await client.open_negotiation(
        thread=_thread(), message=_message(), domain_writes=domain_writes
    )

    assert round_number == 0
    assert _rows(client) == {"negotiation_threads": 1, "negotiation_messages": 1, "domain_opening": 1}
    bound = await client.load_thread_binding(negotiation_id="neg-1")
    assert (bound.listing_id, bound.site_id, bound.binding) == ("listing-a", "site-a", DOMAIN)
    messages = await client.load_negotiation_thread(negotiation_id="neg-1")
    assert [(m["round"], m["action_taken"]) for m in messages] == [(0, "make_offer")]


@pytest.mark.asyncio
async def test_a_failing_last_write_leaves_no_thread_message_or_binding(tmp_path):
    client = await _storefront(tmp_path)
    _rows(client)

    def domain_writes(conn: sqlite3.Connection) -> None:
        conn.execute("INSERT INTO domain_opening (negotiation_id) VALUES (?)", ("neg-1",))
        raise sqlite3.OperationalError("the domain's write failed")

    with pytest.raises(sqlite3.OperationalError):
        await client.open_negotiation(thread=_thread(), message=_message(), domain_writes=domain_writes)

    assert _rows(client) == {"negotiation_threads": 0, "negotiation_messages": 0, "domain_opening": 0}
    assert await client.load_negotiation_thread_row(negotiation_id="neg-1") is None


@pytest.mark.asyncio
async def test_an_opening_on_an_unbound_listing_writes_nothing(tmp_path):
    client = await _storefront(tmp_path)
    await client.upsert_listing(
        listing_id="listing-unbound",
        status="open",
        created_at="2026-08-15T00:00:00Z",
        updated_at="2026-08-15T00:00:00Z",
        listing_resource={"resource_type": "compute.gpu"},
        fulfillment_resource=None,
        max_duration_seconds=3600,
        storefront_url="https://seller.example",
        seller_principal=SELLER,
    )
    _rows(client)

    with pytest.raises(LookupError, match="has no domain binding"):
        await client.open_negotiation(
            thread={**_thread(), "our_listing_id": "listing-unbound"}, message=_message()
        )

    assert _rows(client)["negotiation_threads"] == 0
    assert _rows(client)["negotiation_messages"] == 0


@pytest.mark.asyncio
async def test_the_message_must_belong_to_the_thread(tmp_path):
    client = await _storefront(tmp_path)

    with pytest.raises(ValueError, match="belong to the opening thread"):
        await client.open_negotiation(thread=_thread("neg-1"), message=_message("neg-2"))

    assert _rows(client)["negotiation_threads"] == 0
