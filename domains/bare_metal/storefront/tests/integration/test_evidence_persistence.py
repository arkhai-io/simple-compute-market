"""The evidence repository against independent file-backed SQLite connections."""

from __future__ import annotations

import sqlite3

import pytest

from arkhai_bare_metal import BareMetalLeaseReadyEvidenceDocument, bare_metal_digest
from arkhai_bare_metal.evidence import canonical_bare_metal_json
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient


def document(*, anchor="escrow-a"):
    result = {
        "kind": "bare_metal.lease-ready-result.v1",
        "site_id": "site-a",
        "resource_selection": "specific",
        "physical_resource_id": "resource-a",
        "capacity_reservation_ref": "reservation-a",
        "settlement_resource_ref": "settlement-resource-a",
        "fulfillment_ref": "fulfillment-a",
        "access_ready_at": "2030-01-01T00:40:00+00:00",
        "expires_at": "2030-01-01T00:50:00Z",
    }
    return BareMetalLeaseReadyEvidenceDocument.from_wire(
        {
            "kind": "bare_metal.lease-ready-evidence.v1",
            "accepted_binding_kind": "bare_metal.accepted-alkahest-binding.v1",
            "agreement_ref": "negotiation-a",
            "obligation_ref": "obligation-a",
            "accepted_binding_digest": "sha256:" + "11" * 32,
            "fulfillment_identity": "sha256:" + "22" * 32,
            "buyer_principal": {"scheme": "ed25519", "identifier": "buyer-a"},
            "seller_principal": {"scheme": "ed25519", "identifier": "seller-a"},
            "claimant_principal": {"scheme": "ed25519", "identifier": "claimant-a"},
            "condition_anchor": anchor,
            "result": result,
            "result_digest": bare_metal_digest(result),
        }
    )


def seed(client):
    # Evidence has no public write API; establish only the repository's row.
    with sqlite3.connect(client.db_path) as conn:
        conn.execute(
            "INSERT INTO bare_metal_fulfillment_lifecycle "
            "(negotiation_id, settlement_ref, site_id, physical_resource_id, state) "
            "VALUES ('negotiation-a', 'escrow-a', 'site-a', 'resource-a', 'active')"
        )


def stored(client):
    with sqlite3.connect(client.db_path) as conn:
        return conn.execute(
            "SELECT lease_ready_evidence_json, lease_ready_evidence_digest "
            "FROM bare_metal_fulfillment_lifecycle WHERE negotiation_id='negotiation-a'"
        ).fetchone()


async def test_first_document_wins_and_survives_a_repository_restart(tmp_path):
    path = str(tmp_path / "storefront.db")
    client = SQLiteClient(path)
    seed(client)
    first = document()
    winner = await client.save_bare_metal_lease_ready_evidence(
        negotiation_id="negotiation-a", evidence=first
    )
    assert winner == first
    original = stored(client)
    assert original == (first.canonical_json(), first.evidence_digest)
    assert bare_metal_digest(winner.value) != winner.evidence_digest

    restarted = SQLiteClient(path)
    retried = await restarted.save_bare_metal_lease_ready_evidence(
        negotiation_id="negotiation-a", evidence=document(anchor="another-escrow")
    )
    loaded = await restarted.load_bare_metal_lease_ready_evidence(
        evidence_digest=first.evidence_digest
    )
    assert retried == loaded == first
    assert stored(restarted) == original
    assert (
        await restarted.load_bare_metal_lease_ready_evidence(
            evidence_digest="sha256:" + "ff" * 32
        )
        is None
    )


@pytest.mark.parametrize(
    "corruption", ["empty", "malformed", "nested", "outer", "null-body", "null-digest"]
)
async def test_corruption_is_refused_without_replacing_the_stored_content(
    tmp_path, corruption
):
    client = SQLiteClient(str(tmp_path / "storefront.db"))
    seed(client)
    first = document()
    text, digest = first.canonical_json(), first.evidence_digest
    if corruption == "empty":
        text = ""
    elif corruption == "malformed":
        text = "{"
    elif corruption == "nested":
        wire = first.to_wire()
        wire["result"]["site_id"] = "changed"
        text, digest = canonical_bare_metal_json(wire), bare_metal_digest(wire)
    elif corruption == "outer":
        text = text.replace(
            '"condition_anchor":"escrow-a"', '"condition_anchor":"escrow-b"'
        )
    elif corruption == "null-body":
        text = None
    elif corruption == "null-digest":
        digest = None
    with sqlite3.connect(client.db_path) as conn:
        conn.execute(
            "UPDATE bare_metal_fulfillment_lifecycle SET "
            "lease_ready_evidence_json=?, lease_ready_evidence_digest=?",
            (text, digest),
        )
    original = stored(client)
    if digest is not None:
        with pytest.raises(ValueError):
            await client.load_bare_metal_lease_ready_evidence(evidence_digest=digest)
    with pytest.raises(ValueError):
        await client.save_bare_metal_lease_ready_evidence(
            negotiation_id="negotiation-a", evidence=document(anchor="replacement")
        )
    assert stored(client) == original
