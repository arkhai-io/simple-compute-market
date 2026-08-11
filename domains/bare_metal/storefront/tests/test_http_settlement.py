from __future__ import annotations

import sqlite3
import time

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
from market_core.schemas import SettlementPlan
from market_settlement_runtime import derive_obligation_ref

from arkhai_bare_metal import BareMetalMessage, BareMetalTerms
from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.runtime import BareMetalStorefrontRuntime
from arkhai_bare_metal_storefront.server import build_bare_metal_storefront_app
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient

PRIVATE_KEY = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
BUYER = "0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc"
ESCROW_ADDRESS = "0x1111111111111111111111111111111111111111"
ESCROW_UID = "0x" + "ab" * 32
OTHER_ESCROW_UID = "0x" + "cd" * 32


def _headers(operation: str, resource_id: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    signature = Account.sign_message(
        encode_defunct(text=f"{operation}:{resource_id}:{timestamp}"),
        PRIVATE_KEY,
    ).signature.hex()
    return {
        "X-Timestamp": timestamp,
        "X-Signature": signature,
        "X-Identity": BUYER,
        "X-Identity-Scheme": "eip191",
    }


def _plan(**kwargs):
    expiration_unix = (
        kwargs["proposal"]["expiration_unix"]
        if isinstance(kwargs["proposal"], dict)
        else kwargs["proposal"].expiration_unix
    )
    return {
        "settlement_plan": {
            "obligations": [
                {
                    "payer": "seller",
                    "claimant": "buyer",
                    "amount": 25,
                    "asset": "0x2222222222222222222222222222222222222222",
                    "expiration_unix": expiration_unix,
                    "mechanism": "alkahest.v1",
                    "params": {"chain_name": "anvil", "kind": "seller-bond"},
                },
                {
                    "payer": "buyer",
                    "claimant": "seller",
                    "amount": 100,
                    "asset": "0x2222222222222222222222222222222222222222",
                    "expiration_unix": expiration_unix,
                    "mechanism": "alkahest.v1",
                    "params": {"chain_name": "anvil", "kind": "primary-payment"},
                },
            ],
            "service_terms": {},
        }
    }


async def _accepted_runtime(
    path: str, verifier
) -> tuple[BareMetalStorefrontRuntime, str]:
    domain = get_market_domain_contract()
    db = SQLiteClient(path, domain=domain)
    runtime = BareMetalStorefrontRuntime(
        db=db,
        domain=domain,
        seller_id="0x3333333333333333333333333333333333333333",
        plan_builder=_plan,
        chain_clients={"anvil": object()},
        chain_config_paths={"anvil": None},
        escrow_verifier=verifier,
    )
    await db.upsert_bare_metal_listing(
        listing_id="listing-1",
        status="open",
        created_at="now",
        updated_at="now",
        seller=runtime.seller_id,
        listing={
            "kind": "bare_metal.v1",
            "machine_id": "machine-1",
            "physical_host_id": "host-1",
            "access_methods": ["ssh"],
        },
        accepted_escrows=[],
    )
    negotiation_id = "neg-accepted"
    await db.persist_bare_metal_opening(
        negotiation_id=negotiation_id,
        listing_id="listing-1",
        seller_id=runtime.seller_id,
        buyer_agent_id=BUYER,
        buyer_identity=BUYER,
        seller_reference_amount=100,
        strategy="listed",
        message=BareMetalMessage(
            duration_seconds=3600,
            ssh_public_key="ssh-ed25519 persisted-key",
        ),
        proposal={
            "chain_name": "anvil",
            "escrow_address": ESCROW_ADDRESS,
            "fields": {"amount": "100"},
            "expiration_unix": int(time.time()) + 3600,
        },
        buyer_amount=100,
        seller_action="accept",
        seller_amount=100,
        terms=BareMetalTerms(
            machine_id="machine-1",
            physical_host_id="host-1",
            duration_seconds=3600,
            ssh_public_key="ssh-ed25519 persisted-key",
            listing_ref="listing-1",
        ),
        agreed_amount=100,
    )
    return runtime, negotiation_id


async def test_settlement_is_verified_idempotently_without_fulfillment_claims(
    tmp_path,
) -> None:
    calls = []

    async def verifier(**kwargs):
        calls.append(kwargs)
        return 1

    path = str(tmp_path / "storefront.db")
    runtime, negotiation_id = await _accepted_runtime(path, verifier)
    app = build_bare_metal_storefront_app(runtime=runtime)
    body = {"negotiation_id": negotiation_id, "buyer_address": BUYER}

    with TestClient(app) as client:
        first = client.post(
            f"/api/v1/settle/{ESCROW_UID}",
            json=body,
            headers=_headers("settle_escrow", ESCROW_UID),
        )
        retry = client.post(
            f"/api/v1/settle/{ESCROW_UID}",
            json=body,
            headers=_headers("settle_escrow", ESCROW_UID),
        )
        conflict = client.post(
            f"/api/v1/settle/{OTHER_ESCROW_UID}",
            json=body,
            headers=_headers("settle_escrow", OTHER_ESCROW_UID),
        )

    restarted_domain = get_market_domain_contract()
    restarted = BareMetalStorefrontRuntime(
        db=SQLiteClient(path, domain=restarted_domain),
        domain=restarted_domain,
        seller_id=runtime.seller_id,
        plan_builder=_plan,
        chain_clients={},
        chain_config_paths={"anvil": None},
        escrow_verifier=verifier,
    )
    with TestClient(build_bare_metal_storefront_app(runtime=restarted)) as client:
        restart_retry = client.post(
            f"/api/v1/settle/{ESCROW_UID}",
            json=body,
            headers=_headers("settle_escrow", ESCROW_UID),
        )
        status = client.get(
            f"/api/v1/settle/{ESCROW_UID}/status",
            params={"buyer_address": BUYER},
            headers=_headers("settle_status", ESCROW_UID),
        )

    expected = {
        "escrow_uid": ESCROW_UID,
        "negotiation_id": negotiation_id,
        "status": "settlement_verified",
        "fulfillment_available": False,
    }
    assert first.status_code == 200
    assert first.json() == expected
    assert retry.json() == expected
    assert status.json() == expected
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "negotiation already has a primary escrow"
    assert len(calls) == 1
    assert calls[0]["agreed_duration_seconds"] == 3600
    assert calls[0]["agreed_price"] == 100
    assert "ssh_public_key" not in body
    assert not (
        {"provisioning_job_id", "tenant_credentials", "receipt", "result"}
        & first.json().keys()
    )
    assert restart_retry.json() == expected
    assert restarted.settlement_runtime._clients == {}
    aggregate = await restarted.settlement_runtime.get_status(negotiation_id)
    expiration_unix = aggregate.obligations[1].obligation["expiration_unix"]
    obligations = SettlementPlan.model_validate(
        _plan(proposal={"expiration_unix": expiration_unix})["settlement_plan"]
    ).model_dump(mode="json")["obligations"]
    assert aggregate.status == "active"
    assert len(aggregate.obligations) == 2
    assert aggregate.obligations[0].mechanism_ref is None
    verified = aggregate.obligations[1]
    assert verified.obligation_ref == derive_obligation_ref(
        negotiation_id,
        1,
        obligations[1],
    )
    assert verified.mechanism_ref == ESCROW_UID
    assert verified.materialization_state == "materialized"
    assert verified.mechanism_status == "ready"
    assert verified.mechanism_state == {}
    assert verified.condition_anchor is None
    assert verified.fulfillment_ref is None
    assert verified.condition_state == "pending"
    assert verified.collection_state == "pending"
    assert all(item.fulfillment_ref is None for item in aggregate.obligations)

    conn = sqlite3.connect(path)
    try:
        operations = conn.execute(
            "SELECT operation, state FROM settlement_operations "
            "ORDER BY obligation_ref, operation"
        ).fetchall()
        legacy_claim_table = conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'settlement_claims'"
        ).fetchone()
        legacy_claims = (
            conn.execute("SELECT COUNT(*) FROM settlement_claims").fetchone()[0]
            if legacy_claim_table is not None
            else 0
        )
    finally:
        conn.close()
    assert operations == [("materialize", "succeeded")]
    assert legacy_claims == 0


async def test_settlement_rejects_replacement_access_input_and_failed_verification(
    tmp_path,
) -> None:
    async def verifier(**_kwargs):
        raise ValueError("chain mismatch")

    runtime, negotiation_id = await _accepted_runtime(
        str(tmp_path / "storefront.db"),
        verifier,
    )
    app = build_bare_metal_storefront_app(runtime=runtime)

    with TestClient(app) as client:
        replacement = client.post(
            f"/api/v1/settle/{ESCROW_UID}",
            json={
                "negotiation_id": negotiation_id,
                "buyer_address": BUYER,
                "ssh_public_key": "attacker-key",
            },
            headers=_headers("settle_escrow", ESCROW_UID),
        )
        failed = client.post(
            f"/api/v1/settle/{ESCROW_UID}",
            json={"negotiation_id": negotiation_id, "buyer_address": BUYER},
            headers=_headers("settle_escrow", ESCROW_UID),
        )

    assert replacement.status_code == 422
    assert failed.status_code == 400
    assert await runtime.db.load_escrow(escrow_uid=ESCROW_UID) is None


async def test_settlement_rejects_unmatched_obligation_without_registering_claims(
    tmp_path,
) -> None:
    async def verifier(**_kwargs):
        return 2

    runtime, negotiation_id = await _accepted_runtime(
        str(tmp_path / "storefront.db"),
        verifier,
    )
    with TestClient(build_bare_metal_storefront_app(runtime=runtime)) as client:
        response = client.post(
            f"/api/v1/settle/{ESCROW_UID}",
            json={"negotiation_id": negotiation_id, "buyer_address": BUYER},
            headers=_headers("settle_escrow", ESCROW_UID),
        )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "settlement verification returned no exact obligation"
    )
    assert await runtime.db.load_escrow(escrow_uid=ESCROW_UID) is None
    aggregate = await runtime.settlement_runtime.get_status(negotiation_id)
    assert aggregate.obligations == []


async def test_status_fails_closed_without_canonical_verified_adoption(
    tmp_path,
) -> None:
    async def verifier(**_kwargs):
        raise AssertionError("status must not call a settlement provider")

    runtime, negotiation_id = await _accepted_runtime(
        str(tmp_path / "storefront.db"),
        verifier,
    )
    inserted = await runtime.db.insert_escrow(
        escrow_uid=ESCROW_UID,
        negotiation_id=negotiation_id,
        chain_name="anvil",
        escrow_address=ESCROW_ADDRESS,
        is_primary=True,
        status="settlement_verified",
    )
    assert inserted

    with TestClient(build_bare_metal_storefront_app(runtime=runtime)) as client:
        response = client.get(
            f"/api/v1/settle/{ESCROW_UID}/status",
            params={"buyer_address": BUYER},
            headers=_headers("settle_status", ESCROW_UID),
        )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "verified settlement lifecycle is inconsistent"
    )
