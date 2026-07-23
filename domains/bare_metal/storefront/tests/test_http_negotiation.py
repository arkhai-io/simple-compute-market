from __future__ import annotations

import time

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.runtime import BareMetalStorefrontRuntime
from arkhai_bare_metal_storefront.server import build_bare_metal_storefront_app
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient

PRIVATE_KEY = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
BUYER = "0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc"
ESCROW = "0x1111111111111111111111111111111111111111"
TOKEN = "0x2222222222222222222222222222222222222222"


def _headers(operation: str, resource_id: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    message = f"{operation}:{resource_id}:{timestamp}"
    signature = Account.sign_message(
        encode_defunct(text=message),
        PRIVATE_KEY,
    ).signature.hex()
    return {
        "X-Timestamp": timestamp,
        "X-Signature": signature,
        "X-Identity": BUYER,
        "X-Identity-Scheme": "eip191",
    }


def _runtime(path: str) -> BareMetalStorefrontRuntime:
    domain = get_market_domain_contract()
    return BareMetalStorefrontRuntime(
        db=SQLiteClient(path, domain=domain),
        domain=domain,
        seller_id="seller-1",
        plan_builder=lambda **_kwargs: {
            "settlement_plan": {"obligations": []},
            "accepted_escrow_terms": [],
        },
    )


async def _insert_listing(runtime: BareMetalStorefrontRuntime) -> None:
    await runtime.db.upsert_bare_metal_listing(
        listing_id="listing-1",
        status="open",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        seller="seller-1",
        listing={
            "kind": "bare_metal.v1",
            "machine_id": "machine-1",
            "physical_host_id": "physical-host-1",
            "access_methods": ["ssh"],
            "min_duration_seconds": 60,
            "max_duration_seconds": 7200,
        },
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": ESCROW,
                "literal_fields": {"token": TOKEN},
                "rates": [{"field": "amount", "per": "hour", "value": "100"}],
            },
        ],
    )


def _opening(*, payload: dict | None = None) -> dict:
    return {
        "listing_id": "listing-1",
        "buyer_address": BUYER,
        "buyer_agent_url": "https://buyer.example",
        "provision_terms": {
            "kind": "bare_metal.v1",
            "version": 1,
            "payload": payload
            or {
                "duration_seconds": 3600,
                "access_method": "ssh",
                "ssh_public_key": "ssh-ed25519 buyer-key",
            },
        },
        "proposal": {
            "chain_name": "anvil",
            "escrow_address": ESCROW,
            "fields": {"amount": "100", "token": TOKEN},
            "literal_fields": {"token": TOKEN},
            "expiration_unix": int(time.time()) + 3600,
        },
    }


async def test_signed_opening_accepts_and_persists_domain_artifacts(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    await _insert_listing(runtime)
    app = build_bare_metal_storefront_app(runtime=runtime)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/negotiate/new",
            json=_opening(),
            headers=_headers("negotiate_new", "listing-1"),
        )
        negotiation_id = response.json()["negotiation_id"]
        listing_threads = client.get(
            "/api/v1/listings/listing-1/negotiations",
        )
        detail = client.get(
            f"/api/v1/listings/listing-1/negotiations/{negotiation_id}",
        )

    assert response.status_code == 200
    assert response.json()["action"] == "accept"
    assert response.json()["accepted_provision_terms"] == _opening()["provision_terms"]
    assert response.json()["settlement_plan"] == {
        "obligations": [],
        "service_terms": {},
    }
    assert listing_threads.json()["count"] == 1
    assert detail.json()["terminal_state"] == "success"
    assert detail.json()["round_count"] == 2
    assert (await runtime.db.load_bare_metal_message(
        negotiation_id=negotiation_id,
    )).ssh_public_key == "ssh-ed25519 buyer-key"
    assert (await runtime.db.load_bare_metal_terms(
        negotiation_id=negotiation_id,
    )).machine_id == "machine-1"


async def test_auth_and_domain_failures_write_no_thread(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    await _insert_listing(runtime)
    app = build_bare_metal_storefront_app(runtime=runtime)
    invalid = _opening(
        payload={
            "duration_seconds": 3600,
            "access_method": "ssh",
            "ssh_public_key": "ssh-ed25519 buyer-key",
            "access_ref": {"url": "https://buyer.invalid"},
        },
    )

    with TestClient(app) as client:
        unsigned = client.post("/api/v1/negotiate/new", json=_opening())
        rejected = client.post(
            "/api/v1/negotiate/new",
            json=invalid,
            headers=_headers("negotiate_new", "listing-1"),
        )
        threads = client.get("/api/v1/listings/listing-1/negotiations")

    assert unsigned.status_code == 403
    assert rejected.status_code == 400
    assert threads.json()["count"] == 0


async def test_durable_pause_blocks_new_negotiation(tmp_path) -> None:
    runtime = _runtime(str(tmp_path / "storefront.db"))
    await _insert_listing(runtime)
    await runtime.db.set_global_paused(paused=True)
    app = build_bare_metal_storefront_app(runtime=runtime)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/negotiate/new",
            json=_opening(),
            headers=_headers("negotiate_new", "listing-1"),
        )

    assert response.status_code == 503
