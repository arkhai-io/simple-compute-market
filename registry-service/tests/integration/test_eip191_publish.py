"""Integration tests for the eip191 publish path (Phase 3).

Verifies that POSTing to ``/agents/0x{addr}/listings`` with valid EIP-191
auth lazy-creates an Agent row and publishes the listing — no on-chain
lookup required.
"""

from __future__ import annotations

import time

import httpx
import pytest

from src.db.database import get_db
from src.main import app

pytestmark = pytest.mark.asyncio

# anvil deterministic account 1
PRIVATE_KEY = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
ADDRESS_LOWER = "0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc"


def _sign(message: str) -> str:
    from eth_account import Account
    from eth_account.messages import encode_defunct

    return Account.sign_message(
        encode_defunct(text=message), PRIVATE_KEY
    ).signature.hex()


@pytest.fixture
def asgi_client(db_session):
    """httpx.AsyncClient against the FastAPI app, with in-memory DB."""

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db

    return httpx.AsyncClient(
        base_url="http://test",
        transport=httpx.ASGITransport(app=app),
    ), db_session


async def test_eip191_publish_creates_agent_and_listing(asgi_client):
    client, db = asgi_client
    try:
        ts = int(time.time())
        sig = _sign(f"create_listing:{ADDRESS_LOWER}:{ts}")
        body = {
            "listing_id": "eip191-listing-1",
            "seller": "http://my-storefront/",
            "offer_resource": {"gpu_model": "H200", "region": "us"},
            "accepted_escrows": [{
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "0x" + "22" * 20},
                "rates": [{"field": "amount", "per": "hour", "value": "100"}],
            }],
            "max_duration_seconds": 3600,
            "status": "open",
            "signature": sig,
            "timestamp": ts,
        }
        resp = await client.post(f"/agents/{ADDRESS_LOWER}/listings", json=body)
        assert resp.status_code == 201, resp.text

        # Agent row created
        from src.db.models import Agent, Listing
        agent = db.query(Agent).filter(Agent.scheme == "eip191").first()
        assert agent is not None
        assert agent.identifier == ADDRESS_LOWER
        assert agent.owner == ADDRESS_LOWER

        listing = db.query(Listing).filter(Listing.listing_id == "eip191-listing-1").first()
        assert listing is not None
    finally:
        await client.aclose()
        app.dependency_overrides.clear()


async def test_eip191_publish_rejects_invalid_signature(asgi_client):
    client, _ = asgi_client
    try:
        ts = int(time.time())
        # Sign with a different key
        from eth_account import Account
        from eth_account.messages import encode_defunct

        bad_key = "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a"
        sig = Account.sign_message(
            encode_defunct(text=f"create_listing:{ADDRESS_LOWER}:{ts}"),
            bad_key,
        ).signature.hex()

        body = {
            "listing_id": "eip191-listing-bad-sig",
            "seller": "http://my-storefront/",
            "offer_resource": {},
            "accepted_escrows": [],
            "signature": sig,
            "timestamp": ts,
        }
        resp = await client.post(f"/agents/{ADDRESS_LOWER}/listings", json=body)
        assert resp.status_code == 401, resp.text
    finally:
        await client.aclose()
        app.dependency_overrides.clear()


async def test_eip191_publish_reuses_existing_agent_row(asgi_client):
    """Publishing twice should reuse the same Agent row (idempotent lazy-create)."""
    client, db = asgi_client
    try:
        from src.db.models import Agent

        async def _publish(listing_id: str):
            ts = int(time.time())
            sig = _sign(f"create_listing:{ADDRESS_LOWER}:{ts}")
            body = {
                "listing_id": listing_id,
                "seller": "http://my-storefront/",
                "offer_resource": {},
                "accepted_escrows": [],
                "signature": sig,
                "timestamp": ts,
            }
            return await client.post(f"/agents/{ADDRESS_LOWER}/listings", json=body)

        r1 = await _publish("eip191-listing-a")
        r2 = await _publish("eip191-listing-b")
        assert r1.status_code == 201
        assert r2.status_code == 201

        agents = db.query(Agent).filter(Agent.scheme == "eip191").all()
        assert len(agents) == 1
    finally:
        await client.aclose()
        app.dependency_overrides.clear()
