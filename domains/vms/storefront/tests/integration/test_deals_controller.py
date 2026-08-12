"""Deal heartbeat endpoint: v2 principal proofs, replay protection, and binding."""

from __future__ import annotations

import time

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from market_identity import (
    REQUEST_PROTOCOL,
    Ed25519Signer,
    RequestEnvelope,
    canonical_body_hash,
    sign_request,
)

import market_storefront.container as _container
from market_storefront.utils.sqlite_client import SQLiteClient

BUYER = Ed25519Signer(b"\x31" * 32)
OTHER = Ed25519Signer(b"\x32" * 32)
SELLER = Ed25519Signer(b"\x33" * 32)
ESCROW_UID = "0x" + "ee" * 32


def _body(*, buyer=BUYER, payload=None) -> dict:
    return {
        "buyer_principal": buyer.identity.model_dump(mode="json"),
        "seller_principal": SELLER.identity.model_dump(mode="json"),
        "payload": {} if payload is None else payload,
    }


def _signed_headers(
    *,
    signer,
    body: dict,
    resource: str = ESCROW_UID,
    request_id: str,
    timestamp: int | None = None,
) -> tuple[dict[str, str], int]:
    timestamp = int(time.time()) if timestamp is None else timestamp
    authenticated = sign_request(
        signer=signer,
        envelope=RequestEnvelope(
            role="buyer",
            principal=signer.identity,
            method="POST",
            operation="deal_heartbeat",
            resource=resource,
            request_id=request_id,
            timestamp=timestamp,
            body_hash=canonical_body_hash(body),
        ),
    )
    return {
        "X-Market-Signature-Version": REQUEST_PROTOCOL,
        "X-Market-Identity-Scheme": authenticated.principal.scheme.value,
        "X-Market-Identity-Identifier": authenticated.principal.identifier,
        "X-Market-Role": authenticated.role,
        "X-Market-Request-ID": authenticated.request_id,
        "X-Market-Timestamp": str(authenticated.timestamp),
        "X-Market-Signature": authenticated.proof.value,
    }, timestamp


@pytest_asyncio.fixture
async def client(tmp_path):
    db = SQLiteClient(db_path=str(tmp_path / "deals-test.db"))
    await db.create_negotiation_thread(
        negotiation_id="neg-hb-1",
        our_listing_id="lst-1",
        their_listing_id="",
        our_agent_id=SELLER.identity.identifier,
        their_agent_id=BUYER.identity.identifier,
        buyer_principal=BUYER.identity,
        seller_principal=SELLER.identity,
        owner_id=SELLER.identity.identifier,
    )
    await db.insert_escrow(
        escrow_uid=ESCROW_UID,
        negotiation_id="neg-hb-1",
        chain_name=None,
        escrow_address=None,
        status="ready",
    )
    _container.resolved_sqlite_client = db

    from market_storefront.controllers.deals_controller import router

    app = FastAPI()
    app.include_router(router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, db


@pytest.mark.asyncio
async def test_ed25519_heartbeat_round_trip(client):
    c, db = client
    body = _body()
    headers, timestamp = _signed_headers(
        signer=BUYER,
        body=body,
        request_id="heartbeat-round-trip",
    )
    response = await c.post(
        f"/api/v1/deals/{ESCROW_UID}/heartbeat",
        json=body,
        headers=headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["deal_ref"] == ESCROW_UID
    assert payload["buyer_principal"] == BUYER.identity.model_dump(mode="json")
    assert payload["seller_principal"] == SELLER.identity.model_dump(mode="json")
    assert payload["heartbeat_count"] == 1
    assert payload["sent_at_unix"] == float(timestamp)
    assert payload["next_expected_by_unix"] > float(timestamp)

    stored = await db.latest_heartbeat(ESCROW_UID)
    assert stored["buyer_principal"] == BUYER.identity.model_dump(mode="json")
    assert stored["seller_principal"] == SELLER.identity.model_dump(mode="json")
    assert stored["payload"]["schema"] == "vms.heartbeat.v1"
    assert stored["payload"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_replay_and_body_mutation_are_rejected_before_dispatch(client):
    c, db = client
    body = _body()
    headers, timestamp = _signed_headers(
        signer=BUYER,
        body=body,
        request_id="heartbeat-replay",
    )
    first = await c.post(
        f"/api/v1/deals/{ESCROW_UID}/heartbeat",
        json=body,
        headers=headers,
    )
    assert first.status_code == 200

    replay = await c.post(
        f"/api/v1/deals/{ESCROW_UID}/heartbeat",
        json=body,
        headers=headers,
    )
    assert replay.status_code == 409
    assert await db.count_heartbeats(ESCROW_UID) == 1

    mutated = _body(payload={"status": "mutated"})
    changed_headers, _ = _signed_headers(
        signer=BUYER,
        body=mutated,
        request_id="heartbeat-replay",
        timestamp=timestamp,
    )
    changed = await c.post(
        f"/api/v1/deals/{ESCROW_UID}/heartbeat",
        json=mutated,
        headers=changed_headers,
    )
    assert changed.status_code == 409
    assert "changed signed content" in changed.json()["detail"]
    assert await db.count_heartbeats(ESCROW_UID) == 1

    newer_body = _body()
    newer_headers, _ = _signed_headers(
        signer=BUYER,
        body=newer_body,
        request_id="heartbeat-newer",
        timestamp=timestamp + 1,
    )
    again = await c.post(
        f"/api/v1/deals/{ESCROW_UID}/heartbeat",
        json=newer_body,
        headers=newer_headers,
    )
    assert again.status_code == 200
    assert again.json()["heartbeat_count"] == 2


@pytest.mark.asyncio
async def test_proof_by_another_principal_is_rejected(client):
    c, _db = client
    body = _body()
    headers, _ = _signed_headers(
        signer=OTHER,
        body=body,
        request_id="heartbeat-wrong-proof",
    )
    response = await c.post(
        f"/api/v1/deals/{ESCROW_UID}/heartbeat",
        json=body,
        headers=headers,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_wrong_durable_buyer_binding_is_rejected(client):
    c, _db = client
    body = _body(buyer=OTHER)
    headers, _ = _signed_headers(
        signer=OTHER,
        body=body,
        request_id="heartbeat-wrong-buyer",
    )
    response = await c.post(
        f"/api/v1/deals/{ESCROW_UID}/heartbeat",
        json=body,
        headers=headers,
    )
    assert response.status_code == 403
    assert "buyer" in response.json()["detail"]


@pytest.mark.asyncio
async def test_unknown_deal_is_404(client):
    c, _db = client
    uid = "0x" + "55" * 32
    body = _body()
    headers, _ = _signed_headers(
        signer=BUYER,
        body=body,
        resource=uid,
        request_id="heartbeat-unknown-deal",
    )
    response = await c.post(
        f"/api/v1/deals/{uid}/heartbeat",
        json=body,
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_bad_payload_schema_is_400(client):
    c, _db = client
    body = _body(payload={"schema": "bogus.v9"})
    headers, _ = _signed_headers(
        signer=BUYER,
        body=body,
        request_id="heartbeat-bad-schema",
    )
    response = await c.post(
        f"/api/v1/deals/{ESCROW_UID}/heartbeat",
        json=body,
        headers=headers,
    )
    assert response.status_code == 400
