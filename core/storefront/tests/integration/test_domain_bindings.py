"""Durable listing and negotiation domain bindings on a migrated database.

Library integration: core's client over a real SQLite file its baseline built
(``tests/core_database.py``). The bindings are immutable once written, a
listing names how its capacity is backed, and a close names who closed it;
the client refuses a disagreeing write, and the baseline's triggers refuse one
made in SQL directly.
"""

import asyncio
import base64
import json
import re
import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from core_database import core_database

from market_core import DomainIdentity
from market_identity import Identity, IdentityScheme
from market_resource_pools_contracts.backing import capacity_backing_labels
from core_storefront.domain_registry import (
    StorefrontDomainBinding,
    StorefrontDomainBindingError,
    StorefrontDomainRegistry,
    StorefrontDomainRegistryError,
    StorefrontListingBinding,
    StorefrontThreadBinding,
    build_storefront_derivation_key,
)
from core_storefront.sqlite_client import SQLiteClient, write_listing_update

# The unit suite owns the test contract; this suite reuses it rather than a copy.
from unit.test_domain_registry import _registration


def _principal(byte: int) -> Identity:
    identifier = base64.urlsafe_b64encode(bytes([byte]) * 32).rstrip(b"=").decode()
    return Identity(scheme=IdentityScheme.ED25519, identifier=identifier)


def _client(tmp_path) -> SQLiteClient:
    return SQLiteClient(core_database(tmp_path / "storefront.db"))


def _listing_binding(
    listing_id="listing-a", mode="vm", site="site-a", backing="backed", slice_=1
):
    domain = StorefrontDomainBinding(
        offering_mode=mode,
        domain_identity=DomainIdentity("compute.v1"),
        contract_major=1,
        contract_minor=0,
    )
    return StorefrontListingBinding.from_source_envelope(
        listing_id=listing_id,
        site_id=site,
        pool_id="pool-a",
        binding=domain,
        derivation_key=build_storefront_derivation_key(
            site_id=site,
            offering_mode=mode,
            binding=domain,
            source_identity={"pool_id": "pool-a", "slice": slice_},
        ),
        source_envelope={
            "kind": "vm.listing-source.v1",
            "schema_version": 1,
            "payload": {"pool_id": "pool-a", "slice": slice_},
        },
        last_reconciled_at=datetime.now(UTC).isoformat(),
        capacity_backing=backing,
    )


async def _persist_listing(client, binding, *, status="open"):
    await client.upsert_listing_with_binding(
        binding=binding,
        status=status,
        created_at="2026-08-15T00:00:00Z",
        updated_at="2026-08-15T00:00:00Z",
        listing_resource={
            "resource_type": "compute.gpu",
            "offering_mode": binding.binding.offering_mode,
        },
        fulfillment_resource=None,
        max_duration_seconds=3600,
        storefront_url="https://seller.example",
        seller_principal=_principal(0x11),
    )


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.asyncio
async def test_listing_binding_identical_replay_is_idempotent_and_conflict_rolls_back(
    tmp_path,
):
    client = _client(tmp_path)
    binding = _listing_binding()
    await _persist_listing(client, binding)
    await _persist_listing(client, binding, status="paused")

    assert await client.load_listing_binding(listing_id=binding.listing_id) == binding
    assert (await client.load_listing(listing_id=binding.listing_id))[
        "status"
    ] == "paused"

    changed = StorefrontListingBinding.from_source_envelope(
        listing_id=binding.listing_id,
        site_id="site-b",
        pool_id="pool-a",
        binding=binding.binding,
        derivation_key=build_storefront_derivation_key(
            site_id="site-b",
            offering_mode="vm",
            binding=binding.binding,
            source_identity={"pool_id": "pool-a", "slice": 1},
        ),
        source_envelope=json.loads(binding.source_envelope_json),
        last_reconciled_at=binding.last_reconciled_at,
        capacity_backing=binding.capacity_backing,
    )
    with pytest.raises(StorefrontDomainBindingError, match="different immutable"):
        await _persist_listing(client, changed, status="open")
    assert (await client.load_listing(listing_id=binding.listing_id))["status"] == "paused"


@pytest.mark.asyncio
async def test_public_mode_disagreement_fails_before_listing_or_binding_write(tmp_path):
    client = _client(tmp_path)
    binding = _listing_binding()

    with pytest.raises(StorefrontDomainBindingError, match="offering_mode"):
        await client.upsert_listing_with_binding(
            binding=binding,
            status="open",
            created_at="2026-08-15T00:00:00Z",
            updated_at="2026-08-15T00:00:00Z",
            listing_resource={"offering_mode": "bare_metal"},
            fulfillment_resource=None,
            max_duration_seconds=3600,
            storefront_url="https://seller.example",
            seller_principal=_principal(0x22),
        )
    assert await client.load_listing(listing_id=binding.listing_id) is None


@pytest.mark.asyncio
async def test_opening_copies_binding_message_and_artifact_in_one_transaction(tmp_path):
    client = _client(tmp_path)
    listing_binding = _listing_binding()
    await _persist_listing(client, listing_binding)
    thread_binding = StorefrontThreadBinding(
        negotiation_id="negotiation-a",
        listing_id=listing_binding.listing_id,
        site_id=listing_binding.site_id,
        binding=listing_binding.binding,
    )
    registration = _registration("vm", "compute.v1", "vms")
    registry = StorefrontDomainRegistry((registration,))
    artifact, _ = client.prepare_domain_artifact(
        artifact_slot="message:0",
        value={"kind": "compute.provision.v1", "schema_version": 1, "payload": {}},
        binding=thread_binding.binding,
        registry=registry,
    )
    thread = SimpleNamespace(
        negotiation_id=thread_binding.negotiation_id,
        listing_id=listing_binding.listing_id,
        counterparty_listing_id="buyer-listing-a",
        seller_agent_url="https://seller.example",
        buyer_agent_url="https://buyer.example",
        buyer_principal=_principal(0x33),
        seller_principal=_principal(0x11),
        owner_id="seller",
        seller_initial_amount=100,
        strategy_label="fixed",
        requested_duration_seconds=3600,
        requested_start_utc=None,
        pinned_proposal=None,
        terms_wire={"kind": "compute.provision.v1", "schema_version": 1, "payload": {}},
    )
    message = SimpleNamespace(
        sender_principal=thread.buyer_principal,
        sender_role="buyer",
        seller_amount=100,
        buyer_amount=100,
        proposed_amount=100,
        action_taken="make_offer",
        message_type="offer",
        timestamp="2026-08-15T00:00:01Z",
        round_number=0,
    )

    await client.create_negotiation_opening(
        thread=thread,
        initial_message=message,
        binding=thread_binding,
        domain_artifact=artifact,
    )

    assert (
        await client.load_thread_binding(negotiation_id=thread_binding.negotiation_id)
        == thread_binding
    )
    assert await client.load_domain_artifact(
        negotiation_id=thread_binding.negotiation_id,
        artifact_slot="message:0",
        registry=registry,
    ) == {
        "kind": "compute.provision.v1",
        "schema_version": 1,
        "payload": {},
    }

    quoted_terms = {"kind": "opaque.v1", "version": 1, "payload": {"units": 3}}
    exact_amount = 2**100 + 3
    await client.save_negotiation_message(
        negotiation_id=thread_binding.negotiation_id,
        sender_principal=thread.seller_principal,
        sender_role="seller",
        our_price=exact_amount,
        their_price=exact_amount - 1,
        proposed_price=exact_amount,
        action_taken="counter_offer",
        message_type="counter_proposal",
        timestamp="2026-08-15T00:00:02Z",
        provision_terms=quoted_terms,
    )
    resumed = SQLiteClient(str(tmp_path / "storefront.db"))
    transcript = await resumed.load_negotiation_thread(
        negotiation_id=thread_binding.negotiation_id
    )
    assert transcript[-1]["provision_terms"] == quoted_terms
    assert transcript[-1]["proposed_price"] == exact_amount
    opening = await resumed.load_negotiation_thread_row(
        negotiation_id=thread_binding.negotiation_id
    )
    assert opening["provision_terms"] == thread.terms_wire

    settlement_data = {
        "transaction_id": "a" * 64,
        "mandate": {"from": "buyer-account", "to": "seller-account"},
    }
    await client.commit_agreed_terms(
        negotiation_id=thread_binding.negotiation_id,
        negotiated_scalar=100,
        agreed_duration_seconds=3600,
        settlement_data=settlement_data,
    )
    accepted = await client.load_negotiation_thread_row(
        negotiation_id=thread_binding.negotiation_id
    )
    assert accepted["settlement_data"] == settlement_data
    assert accepted["negotiated_scalar"] == 100


@pytest.mark.asyncio
async def test_thread_and_artifact_cross_swaps_fail_before_mutation(tmp_path):
    client = _client(tmp_path)
    binding = _listing_binding()
    await _persist_listing(client, binding)
    other = StorefrontThreadBinding(
        negotiation_id="negotiation-a",
        listing_id=binding.listing_id,
        site_id=binding.site_id,
        binding=StorefrontDomainBinding(
            offering_mode="bare_metal",
            domain_identity=DomainIdentity("bare_metal.v1"),
            contract_major=1,
            contract_minor=0,
        ),
    )

    with pytest.raises((sqlite3.IntegrityError, StorefrontDomainBindingError)):
        await client.create_negotiation_thread(
            negotiation_id=other.negotiation_id,
            our_listing_id=other.listing_id,
            their_listing_id="buyer-listing",
            our_agent_id="https://seller.example",
            their_agent_id="https://buyer.example",
            buyer_principal=_principal(0x33),
            seller_principal=_principal(0x11),
            owner_id="seller",
            binding=other,
        )
    with sqlite3.connect(client.db_path) as conn:
        assert (
            conn.execute(
                "SELECT 1 FROM negotiation_threads WHERE negotiation_id=?",
                (other.negotiation_id,),
            ).fetchone()
            is None
        )


def test_direct_sql_binding_mutation_is_rejected(tmp_path):
    client = _client(tmp_path)
    binding = _listing_binding()
    _run(_persist_listing(client, binding))
    with (
        sqlite3.connect(client.db_path) as conn,
        pytest.raises(sqlite3.IntegrityError, match="immutable"),
    ):
        conn.execute(
            "UPDATE storefront_listing_bindings SET site_id='site-b' "
            "WHERE listing_id=?",
            (binding.listing_id,),
        )


def test_binding_backing_cannot_change_after_binding(tmp_path):
    client = _client(tmp_path)
    binding = _listing_binding()
    _run(_persist_listing(client, binding))
    with sqlite3.connect(client.db_path) as conn, pytest.raises(
        sqlite3.IntegrityError, match="immutable"
    ):
        conn.execute(
            "UPDATE storefront_listing_bindings SET capacity_backing='unbacked' "
            "WHERE listing_id=?",
            (binding.listing_id,),
        )


def test_binding_insert_naming_no_backing_is_refused(tmp_path):
    client = _client(tmp_path)
    binding = _listing_binding()
    _run(_persist_listing(client, binding))
    with sqlite3.connect(client.db_path) as conn:
        conn.execute("DELETE FROM storefront_listing_bindings")
        with pytest.raises(sqlite3.IntegrityError, match="capacity_backing"):
            conn.execute(
                """
                INSERT INTO storefront_listing_bindings(
                  listing_id, site_id, pool_id, physical_resource_id,
                  offering_mode, domain_identity, contract_major,
                  contract_minor, derivation_key, source_envelope_json,
                  last_reconciled_at
                ) VALUES (?, ?, ?, NULL, ?, ?, 1, 0, ?, ?, ?)
                """,
                (
                    binding.listing_id,
                    binding.site_id,
                    binding.pool_id,
                    "vm",
                    "compute.v1",
                    binding.derivation_key,
                    binding.source_envelope_json,
                    binding.last_reconciled_at,
                ),
            )


def test_binding_model_refuses_an_unknown_backing():
    with pytest.raises(Exception, match="capacity_backing"):
        _listing_binding(backing="Backed")


def test_second_bind_with_opposite_backing_is_refused(tmp_path):
    client = _client(tmp_path)
    binding = _listing_binding()
    _run(_persist_listing(client, binding))
    opposite = StorefrontListingBinding.from_source_envelope(
        listing_id=binding.listing_id,
        site_id=binding.site_id,
        pool_id=binding.pool_id,
        binding=binding.binding,
        derivation_key=binding.derivation_key,
        source_envelope=json.loads(binding.source_envelope_json),
        last_reconciled_at=binding.last_reconciled_at,
        capacity_backing="unbacked",
    )
    with pytest.raises(StorefrontDomainBindingError):
        _run(_persist_listing(client, opposite))
    assert _run(client.load_listing_binding(listing_id=binding.listing_id)) == binding


def test_direct_sql_close_without_reason_is_refused(tmp_path):
    client = _client(tmp_path)
    binding = _listing_binding()
    _run(_persist_listing(client, binding))
    with sqlite3.connect(client.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="closed_by"):
            conn.execute(
                "UPDATE listings SET status='closed' WHERE listing_id=?",
                (binding.listing_id,),
            )
        conn.execute(
            "UPDATE listings SET status='closed', closed_by='reconciliation' "
            "WHERE listing_id=?",
            (binding.listing_id,),
        )
        with pytest.raises(sqlite3.IntegrityError, match="closed_by"):
            conn.execute(
                "UPDATE listings SET status='open' WHERE listing_id=?",
                (binding.listing_id,),
            )


def test_the_database_check_admits_exactly_the_registered_backing_labels(tmp_path):
    # The column check is a backstop beneath the binding's validation through
    # the backing registry; the two value sets must not drift.
    client = _client(tmp_path)
    with sqlite3.connect(client.db_path) as conn:
        (ddl,) = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='storefront_listing_bindings'"
        ).fetchone()

    match = re.search(r"capacity_backing\s+IN\s*\(([^)]*)\)", ddl)
    assert match is not None, ddl
    checked = {value.strip().strip("'") for value in match.group(1).split(",")}
    assert checked == capacity_backing_labels()


def test_a_binding_with_an_unregistered_backing_is_refused():
    with pytest.raises(StorefrontDomainRegistryError, match="capacity_backing"):
        _listing_binding(backing="sometimes")


_STRUCTURE = {"gpu": [{"asset": "usd", "rate": "2", "per": "hour"}]}


def test_a_listing_update_writes_clears_and_otherwise_keeps_its_rate_structure(tmp_path):
    client = _client(tmp_path)
    binding = _listing_binding()
    _run(_persist_listing(client, binding))

    def stored(conn):
        return conn.execute(
            "SELECT rate_structure FROM listings WHERE listing_id = ?", (binding.listing_id,)
        ).fetchone()[0]

    with sqlite3.connect(client.db_path) as conn:
        assert stored(conn) is None
        write_listing_update(conn, listing_id=binding.listing_id, rate_structure=_STRUCTURE)
        assert json.loads(stored(conn)) == _STRUCTURE

        write_listing_update(conn, listing_id=binding.listing_id, max_duration_seconds=60)
        assert json.loads(stored(conn)) == _STRUCTURE

        write_listing_update(conn, listing_id=binding.listing_id, rate_structure=None)
        assert stored(conn) is None
