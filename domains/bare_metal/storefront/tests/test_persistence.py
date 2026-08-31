from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from arkhai_bare_metal import (
    BareMetalAccessResult,
    BareMetalListing,
    BareMetalMaterialization,
    BareMetalMessage,
    BareMetalReceipt,
    BareMetalTerms,
)
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient
from market_identity import Ed25519Signer


NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
LATER = NOW + timedelta(hours=1)
SELLER = Ed25519Signer(bytes.fromhex("22" * 32)).identity
BUYER = Ed25519Signer(bytes.fromhex("11" * 32)).identity


def _artifacts():
    return {
        "message": BareMetalMessage(
            duration_seconds=3600,
            ssh_public_key="ssh-ed25519 buyer",
        ),
        "terms": BareMetalTerms(
            machine_id="machine-1",
            physical_host_id="host-1",
            duration_seconds=3600,
            ssh_public_key="ssh-ed25519 buyer",
            listing_ref="listing-1",
        ),
        "materialization": BareMetalMaterialization(
            escrow_uid="escrow-1",
            machine_id="machine-1",
            physical_host_id="host-1",
            lease_start_utc=NOW,
            lease_end_utc=LATER,
            ssh_public_key="ssh-ed25519 buyer",
            listing_ref="listing-1",
        ),
        "receipt": BareMetalReceipt(
            escrow_uid="escrow-1",
            machine_id="machine-1",
            physical_host_id="host-1",
            lease_start_utc=NOW,
            lease_end_utc=LATER,
            status="fulfilled",
            result_ref={"result_id": "result-1"},
        ),
        "result": BareMetalAccessResult(
            action="node_grant_access",
            machine_id="machine-1",
            physical_host_id="host-1",
            ssh_user="tenant-1",
            status="success",
        ),
    }


async def _seed_listing(client: SQLiteClient) -> BareMetalListing:
    listing = BareMetalListing(
        machine_id="machine-1",
        physical_host_id="host-1",
        min_duration_seconds=900,
        max_duration_seconds=7200,
    )
    await client.upsert_bare_metal_listing(
        listing_id="listing-1",
        status="open",
        created_at=NOW.isoformat(),
        updated_at=NOW.isoformat(),
        seller_principal=SELLER,
        storefront_url="http://seller:8000",
        site_id="site-a",
        pool_id="pool-a",
        physical_resource_id="resource-1",
        listing=listing,
        accepted_escrows=[],
    )
    return listing


async def _seed_opening(
    client: SQLiteClient,
    *,
    negotiation_id: str,
    message: BareMetalMessage,
    terms: BareMetalTerms | None,
) -> None:
    await client.persist_bare_metal_opening(
        negotiation_id=negotiation_id,
        listing_id="listing-1",
        seller_principal=SELLER,
        buyer_agent_id="https://buyer.example",
        buyer_principal=BUYER,
        seller_reference_amount=100,
        strategy="listed",
        message=message,
        proposal={"fields": {"amount": "100"}},
        buyer_amount=100,
        seller_action="accept" if terms is not None else "counter",
        seller_amount=100,
        terms=terms,
        agreed_amount=100 if terms is not None else None,
    )


@pytest.mark.asyncio
async def test_all_domain_payloads_round_trip_after_restart(tmp_path) -> None:
    path = tmp_path / "storefront.db"
    client = SQLiteClient(str(path))
    listing = await _seed_listing(client)
    artifacts = _artifacts()
    await _seed_opening(
        client,
        negotiation_id="neg-1",
        message=artifacts["message"],
        terms=artifacts["terms"],
    )
    await client.save_bare_metal_message(
        negotiation_id="neg-1",
        message=artifacts["message"],
    )
    await client.save_bare_metal_terms(
        negotiation_id="neg-1",
        terms=artifacts["terms"],
    )
    await client.save_bare_metal_materialization(
        negotiation_id="neg-1",
        materialization=artifacts["materialization"],
    )
    await client.save_bare_metal_receipt(
        negotiation_id="neg-1",
        receipt=artifacts["receipt"],
    )
    await client.save_bare_metal_result(
        negotiation_id="neg-1",
        result=artifacts["result"],
    )

    restarted = SQLiteClient(str(path))
    persisted = await restarted.load_listing(listing_id="listing-1")
    assert persisted is not None
    raw_offer = persisted["offer_resource"]
    offer = json.loads(raw_offer) if isinstance(raw_offer, str) else raw_offer
    assert offer["virtualization_type"] == "bare_metal"


    assert (
        await restarted.load_bare_metal_listing_payload(
            listing_id="listing-1",
        )
        == listing
    )
    assert (
        await restarted.load_bare_metal_message(
            negotiation_id="neg-1",
        )
        == artifacts["message"]
    )
    assert (
        await restarted.load_bare_metal_terms(
            negotiation_id="neg-1",
        )
        == artifacts["terms"]
    )
    assert (
        await restarted.load_bare_metal_materialization(
            negotiation_id="neg-1",
        )
        == artifacts["materialization"]
    )
    assert (
        await restarted.load_bare_metal_receipt(
            negotiation_id="neg-1",
        )
        == artifacts["receipt"]
    )
    assert (
        await restarted.load_bare_metal_result(
            negotiation_id="neg-1",
        )
        == artifacts["result"]
    )


@pytest.mark.asyncio
async def test_artifact_updates_are_isolated_by_column_and_negotiation(
    tmp_path,
) -> None:
    client = SQLiteClient(str(tmp_path / "storefront.db"))
    await _seed_listing(client)
    artifacts = _artifacts()
    await _seed_opening(
        client,
        negotiation_id="neg-1",
        message=artifacts["message"],
        terms=artifacts["terms"],
    )
    await client.save_bare_metal_message(
        negotiation_id="neg-1",
        message=artifacts["message"],
    )
    await client.save_bare_metal_terms(
        negotiation_id="neg-1",
        terms=artifacts["terms"],
    )
    other = BareMetalMessage(
        duration_seconds=1800,
        ssh_public_key="ssh-ed25519 other",
    )
    await _seed_opening(
        client,
        negotiation_id="neg-2",
        message=other,
        terms=None,
    )
    await client.save_bare_metal_message(
        negotiation_id="neg-2",
        message=other,
    )

    assert (
        await client.load_bare_metal_terms(
            negotiation_id="neg-1",
        )
        == artifacts["terms"]
    )
    assert (
        await client.load_bare_metal_message(
            negotiation_id="neg-2",
        )
        == other
    )
    assert await client.load_bare_metal_terms(negotiation_id="neg-2") is None


@pytest.mark.asyncio
async def test_invalid_payload_is_rejected_before_write(tmp_path) -> None:
    path = tmp_path / "storefront.db"
    client = SQLiteClient(str(path))

    with pytest.raises(ValidationError):
        await client.save_bare_metal_message(
            negotiation_id="neg-invalid",
            message={"duration_seconds": 0, "ssh_public_key": "key"},
        )

    conn = sqlite3.connect(path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM storefront_domain_artifacts",
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 0


@pytest.mark.asyncio
async def test_corrupt_stored_json_fails_closed(tmp_path) -> None:
    path = tmp_path / "storefront.db"
    client = SQLiteClient(str(path))
    await _seed_listing(client)
    artifacts = _artifacts()
    await _seed_opening(
        client,
        negotiation_id="neg-corrupt",
        message=artifacts["message"],
        terms=artifacts["terms"],
    )
    conn = sqlite3.connect(path)
    try:
        conn.execute("DROP TRIGGER storefront_domain_artifact_immutable")
        conn.execute(
            "UPDATE storefront_domain_artifacts SET artifact_json=? "
            "WHERE negotiation_id=? AND artifact_slot='message'",
            ("{not-json", "neg-corrupt"),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(json.JSONDecodeError):
        await client.load_bare_metal_message(negotiation_id="neg-corrupt")


def test_common_artifact_table_contains_only_opaque_artifact_columns(tmp_path) -> None:
    path = tmp_path / "storefront.db"
    SQLiteClient(str(path))
    conn = sqlite3.connect(path)
    try:
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(storefront_domain_artifacts)",
            )
        }
    finally:
        conn.close()

    assert columns == {
        "negotiation_id",
        "artifact_slot",
        "offering_mode",
        "domain_identity",
        "contract_major",
        "contract_minor",
        "artifact_json",
        "created_at",
    }
    forbidden = {"vm_host", "vm_target", "ssh_public_key", "machine_id"}
    assert columns.isdisjoint(forbidden)
