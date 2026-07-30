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


NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
LATER = NOW + timedelta(hours=1)


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


@pytest.mark.asyncio
async def test_all_domain_payloads_round_trip_after_restart(tmp_path) -> None:
    path = tmp_path / "storefront.db"
    client = SQLiteClient(str(path))
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
        seller="seller-1",
        listing=listing,
        accepted_escrows=[],
    )
    artifacts = _artifacts()
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

    assert await restarted.load_bare_metal_listing_payload(
        listing_id="listing-1",
    ) == listing
    assert await restarted.load_bare_metal_message(
        negotiation_id="neg-1",
    ) == artifacts["message"]
    assert await restarted.load_bare_metal_terms(
        negotiation_id="neg-1",
    ) == artifacts["terms"]
    assert await restarted.load_bare_metal_materialization(
        negotiation_id="neg-1",
    ) == artifacts["materialization"]
    assert await restarted.load_bare_metal_receipt(
        negotiation_id="neg-1",
    ) == artifacts["receipt"]
    assert await restarted.load_bare_metal_result(
        negotiation_id="neg-1",
    ) == artifacts["result"]


@pytest.mark.asyncio
async def test_artifact_updates_are_isolated_by_column_and_negotiation(
    tmp_path,
) -> None:
    client = SQLiteClient(str(tmp_path / "storefront.db"))
    artifacts = _artifacts()
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
    await client.save_bare_metal_message(
        negotiation_id="neg-2",
        message=other,
    )

    assert await client.load_bare_metal_terms(
        negotiation_id="neg-1",
    ) == artifacts["terms"]
    assert await client.load_bare_metal_message(
        negotiation_id="neg-2",
    ) == other
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
            "SELECT COUNT(*) FROM bare_metal_agreement_payloads",
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 0


@pytest.mark.asyncio
async def test_corrupt_stored_json_fails_closed(tmp_path) -> None:
    path = tmp_path / "storefront.db"
    client = SQLiteClient(str(path))
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO bare_metal_agreement_payloads"
            "(negotiation_id, message_json) VALUES (?, ?)",
            ("neg-corrupt", "{not-json"),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(json.JSONDecodeError):
        await client.load_bare_metal_message(negotiation_id="neg-corrupt")


def test_agreement_table_contains_only_opaque_artifact_columns(tmp_path) -> None:
    path = tmp_path / "storefront.db"
    SQLiteClient(str(path))
    conn = sqlite3.connect(path)
    try:
        columns = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(bare_metal_agreement_payloads)",
            )
        }
    finally:
        conn.close()

    assert columns == {
        "negotiation_id",
        "message_json",
        "terms_json",
        "materialization_json",
        "receipt_json",
        "result_json",
        "created_at",
        "updated_at",
    }
    forbidden = {"vm_host", "vm_target", "ssh_public_key", "machine_id"}
    assert columns.isdisjoint(forbidden)
