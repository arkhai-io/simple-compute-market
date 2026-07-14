"""Deal heartbeat endpoint: real signatures, replay protection, binding."""

from __future__ import annotations

import time

import httpx
import pytest
import pytest_asyncio
from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import FastAPI

import market_storefront.container as _container
from market_storefront.utils.sqlite_client import SQLiteClient

BUYER_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
BUYER_ADDR = Account.from_key(BUYER_KEY).address
OTHER_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
OTHER_ADDR = Account.from_key(OTHER_KEY).address

ESCROW_UID = "0x" + "ee" * 32


def _signed_headers(operation: str, resource_id: str, key: str, ts: int | None = None):
    ts = int(time.time()) if ts is None else ts
    msg = f"{operation}:{resource_id}:{ts}"
    sig = Account.sign_message(encode_defunct(text=msg), key).signature.hex()
    if not sig.startswith("0x"):
        sig = "0x" + sig
    return {"X-Signature": sig, "X-Timestamp": str(ts)}, ts


@pytest_asyncio.fixture
async def client(tmp_path):
    db = SQLiteClient(db_path=str(tmp_path / "deals-test.db"))
    await db.insert_escrow(
        escrow_uid=ESCROW_UID,
        negotiation_id="neg-hb-1",
        chain_name="anvil",
        escrow_address="0x" + "11" * 20,
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
async def test_signed_heartbeat_round_trip(client):
    c, db = client
    headers, ts = _signed_headers("deal_heartbeat", ESCROW_UID, BUYER_KEY)
    resp = await c.post(
        f"/api/v1/deals/{ESCROW_UID}/heartbeat",
        json={"buyer_address": BUYER_ADDR},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deal_ref"] == ESCROW_UID
    assert body["heartbeat_count"] == 1
    assert body["sent_at_unix"] == float(ts)
    assert body["next_expected_by_unix"] > float(ts)

    stored = await db.latest_heartbeat(ESCROW_UID)
    assert stored["signer"] == BUYER_ADDR
    assert stored["payload"]["schema"] == "vms.heartbeat.v1"
    assert stored["payload"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_replayed_request_is_rejected(client):
    c, _db = client
    headers, _ts = _signed_headers("deal_heartbeat", ESCROW_UID, BUYER_KEY)
    first = await c.post(
        f"/api/v1/deals/{ESCROW_UID}/heartbeat",
        json={"buyer_address": BUYER_ADDR},
        headers=headers,
    )
    assert first.status_code == 200
    replay = await c.post(
        f"/api/v1/deals/{ESCROW_UID}/heartbeat",
        json={"buyer_address": BUYER_ADDR},
        headers=headers,
    )
    assert replay.status_code == 409

    # A strictly newer heartbeat goes through.
    newer, _ = _signed_headers(
        "deal_heartbeat", ESCROW_UID, BUYER_KEY, ts=int(time.time()) + 1
    )
    again = await c.post(
        f"/api/v1/deals/{ESCROW_UID}/heartbeat",
        json={"buyer_address": BUYER_ADDR},
        headers=newer,
    )
    assert again.status_code == 200
    assert again.json()["heartbeat_count"] == 2


@pytest.mark.asyncio
async def test_bad_signature_is_403(client):
    c, _db = client
    # Signed by a different key than the claimed address.
    headers, _ = _signed_headers("deal_heartbeat", ESCROW_UID, OTHER_KEY)
    resp = await c.post(
        f"/api/v1/deals/{ESCROW_UID}/heartbeat",
        json={"buyer_address": BUYER_ADDR},
        headers=headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_wrong_buyer_binding_is_403(client):
    c, db = client
    # Record the deal's buyer on the negotiation thread, then heartbeat
    # with a different (validly signing) wallet.
    await db.create_negotiation_thread(
        negotiation_id="neg-hb-1",
        our_listing_id="lst-1",
        their_listing_id="",
        our_agent_id="seller",
        their_agent_id=BUYER_ADDR,
        owner_id="seller",
    )
    import sqlite3

    conn = sqlite3.connect(db.db_path)
    conn.execute(
        "UPDATE negotiation_threads SET buyer = ? WHERE negotiation_id = ?",
        (BUYER_ADDR, "neg-hb-1"),
    )
    conn.commit()
    conn.close()
    headers, _ = _signed_headers("deal_heartbeat", ESCROW_UID, OTHER_KEY)
    resp = await c.post(
        f"/api/v1/deals/{ESCROW_UID}/heartbeat",
        json={"buyer_address": OTHER_ADDR},
        headers=headers,
    )
    assert resp.status_code == 403
    assert "buyer" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_unknown_deal_is_404(client):
    c, _db = client
    uid = "0x" + "55" * 32
    headers, _ = _signed_headers("deal_heartbeat", uid, BUYER_KEY)
    resp = await c.post(
        f"/api/v1/deals/{uid}/heartbeat",
        json={"buyer_address": BUYER_ADDR},
        headers=headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_bad_payload_schema_is_400(client):
    c, _db = client
    headers, _ = _signed_headers("deal_heartbeat", ESCROW_UID, BUYER_KEY)
    resp = await c.post(
        f"/api/v1/deals/{ESCROW_UID}/heartbeat",
        json={"buyer_address": BUYER_ADDR, "payload": {"schema": "bogus.v9"}},
        headers=headers,
    )
    assert resp.status_code == 400
