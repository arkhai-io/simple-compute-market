import json
import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from market_core import DomainIdentity
from market_identity import Identity, IdentityScheme
from core_storefront.domain_registry import (
    StorefrontDomainBinding,
    StorefrontDomainBindingError,
    StorefrontDomainRegistry,
    StorefrontListingBinding,
    StorefrontThreadBinding,
    build_storefront_derivation_key,
)
from core_storefront.sqlite_client import SQLiteClient
from core_storefront.sqlite_migrations import (
    LegacyMigrationInputs,
    _backfill_accepted_escrows,
)

from test_domain_registry import _registration


def _principal(identifier: str) -> Identity:
    return Identity(scheme=IdentityScheme.ED25519, identifier=identifier)


def _listing_binding(listing_id="listing-a", mode="vm", site="site-a"):
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
            source_identity={"pool_id": "pool-a", "slice": 1},
        ),
        source_envelope={
            "kind": "vm.listing-source.v1",
            "schema_version": 1,
            "payload": {"pool_id": "pool-a", "slice": 1},
        },
        last_reconciled_at=datetime.now(UTC).isoformat(),
    )


async def _persist_listing(client, binding, *, status="open"):
    await client.upsert_listing_with_binding(
        binding=binding,
        status=status,
        created_at="2026-08-15T00:00:00Z",
        updated_at="2026-08-15T00:00:00Z",
        offer_resource={
            "resource_type": "compute.gpu",
            "virtualization_type": binding.binding.offering_mode,
        },
        fulfillment_resource=None,
        max_duration_seconds=3600,
        storefront_url="https://seller.example",
        seller_principal=_principal("11" * 32),
    )


@pytest.mark.asyncio
async def test_listing_binding_identical_replay_is_idempotent_and_conflict_rolls_back(
    tmp_path,
):
    client = SQLiteClient(str(tmp_path / "storefront.db"))
    binding = _listing_binding()
    await _persist_listing(client, binding)
    await _persist_listing(client, binding, status="paused")

    assert await client.load_listing_binding(listing_id=binding.listing_id) == binding
    assert (await client.load_listing(listing_id=binding.listing_id))["status"] == "paused"

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
    )
    with pytest.raises(StorefrontDomainBindingError, match="different immutable"):
        await _persist_listing(client, changed, status="closed")
    assert (await client.load_listing(listing_id=binding.listing_id))["status"] == "paused"


@pytest.mark.asyncio
async def test_public_mode_disagreement_fails_before_listing_or_binding_write(tmp_path):
    client = SQLiteClient(str(tmp_path / "storefront.db"))
    binding = _listing_binding()

    with pytest.raises(StorefrontDomainBindingError, match="virtualization_type"):
        await client.upsert_listing_with_binding(
            binding=binding,
            status="open",
            created_at="2026-08-15T00:00:00Z",
            updated_at="2026-08-15T00:00:00Z",
            offer_resource={"virtualization_type": "bare_metal"},
            fulfillment_resource=None,
            max_duration_seconds=3600,
            storefront_url="https://seller.example",
            seller_principal=_principal("22" * 32),
        )
    assert await client.load_listing(listing_id=binding.listing_id) is None


@pytest.mark.asyncio
async def test_opening_copies_binding_message_and_artifact_in_one_transaction(tmp_path):
    client = SQLiteClient(str(tmp_path / "storefront.db"))
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
        buyer_principal=_principal("33" * 32),
        seller_principal=_principal("11" * 32),
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

    assert await client.load_thread_binding(
        negotiation_id=thread_binding.negotiation_id
    ) == thread_binding
    assert await client.load_domain_artifact(
        negotiation_id=thread_binding.negotiation_id,
        artifact_slot="message:0",
        registry=registry,
    ) == {
        "kind": "compute.provision.v1",
        "schema_version": 1,
        "payload": {},
    }


@pytest.mark.asyncio
async def test_thread_and_artifact_cross_swaps_fail_before_mutation(tmp_path):
    client = SQLiteClient(str(tmp_path / "storefront.db"))
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
            buyer_principal=_principal("33" * 32),
            seller_principal=_principal("11" * 32),
            owner_id="seller",
            binding=other,
        )
    with sqlite3.connect(client.db_path) as conn:
        assert conn.execute(
            "SELECT 1 FROM negotiation_threads WHERE negotiation_id=?",
            (other.negotiation_id,),
        ).fetchone() is None


def test_direct_sql_binding_mutation_is_rejected(tmp_path):
    client = SQLiteClient(str(tmp_path / "storefront.db"))
    binding = _listing_binding()
    import asyncio

    asyncio.run(_persist_listing(client, binding))
    with sqlite3.connect(client.db_path) as conn, pytest.raises(
        sqlite3.IntegrityError, match="immutable"
    ):
        conn.execute(
            "UPDATE storefront_listing_bindings SET site_id='site-b' "
            "WHERE listing_id=?",
            (binding.listing_id,),
        )


def test_legacy_synthesizers_are_explicit_per_database():
    first = sqlite3.connect(":memory:")
    second = sqlite3.connect(":memory:")
    for conn in (first, second):
        conn.execute(
            "CREATE TABLE listings (listing_id TEXT PRIMARY KEY, "
            "demand_resource TEXT, accepted_escrows TEXT)"
        )
        conn.execute(
            "INSERT INTO listings VALUES ('listing', '{}', NULL)"
        )

    _backfill_accepted_escrows(
        first,
        LegacyMigrationInputs(
            accepted_escrows_synthesizer=lambda _value: [{"rail": "first"}]
        ),
    )
    _backfill_accepted_escrows(
        second,
        LegacyMigrationInputs(
            accepted_escrows_synthesizer=lambda _value: [{"rail": "second"}]
        ),
    )

    assert json.loads(first.execute(
        "SELECT accepted_escrows FROM listings"
    ).fetchone()[0]) == [{"rail": "first"}]
    assert json.loads(second.execute(
        "SELECT accepted_escrows FROM listings"
    ).fetchone()[0]) == [{"rail": "second"}]
