"""Integration tests for the signed publish path.

POSTing to ``/listings`` with valid EIP-191 auth lazy-creates a publisher
(plus its identity) and the listing — no pre-registration.
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


def _publish_body(listing_id: str, **overrides) -> dict:
    ts = int(time.time())
    sig = _sign(f"create_listing:{ADDRESS_LOWER}:{ts}")
    body = {
        "listing_id": listing_id,
        "scheme": "eip191",
        "identifier": ADDRESS_LOWER,
        "storefront_url": "http://my-storefront/",
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
    body.update(overrides)
    return body


async def test_publish_creates_publisher_and_listing(asgi_client):
    client, db = asgi_client
    try:
        resp = await client.post("/listings", json=_publish_body("eip191-listing-1"))
        assert resp.status_code == 201, resp.text

        from src.db.models import Publisher, PublisherIdentity, Listing
        identity = db.query(PublisherIdentity).filter(PublisherIdentity.scheme == "eip191").first()
        assert identity is not None
        assert identity.identifier == ADDRESS_LOWER

        publisher = db.query(Publisher).filter(Publisher.publisher_id == identity.publisher_id).first()
        assert publisher is not None
        assert publisher.storefront_url == "http://my-storefront/"

        listing = db.query(Listing).filter(Listing.listing_id == "eip191-listing-1").first()
        assert listing is not None
        assert listing.publisher_id == publisher.publisher_id
    finally:
        await client.aclose()
        app.dependency_overrides.clear()


async def test_publish_rejects_invalid_signature(asgi_client):
    client, _ = asgi_client
    try:
        ts = int(time.time())
        from eth_account import Account
        from eth_account.messages import encode_defunct

        bad_key = "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a"
        sig = Account.sign_message(
            encode_defunct(text=f"create_listing:{ADDRESS_LOWER}:{ts}"),
            bad_key,
        ).signature.hex()

        body = _publish_body("eip191-listing-bad-sig", signature=sig, timestamp=ts)
        resp = await client.post("/listings", json=body)
        assert resp.status_code == 401, resp.text
    finally:
        await client.aclose()
        app.dependency_overrides.clear()


async def test_publish_reuses_existing_publisher(asgi_client):
    """Publishing twice reuses the same publisher (idempotent lazy-create)."""
    client, db = asgi_client
    try:
        from src.db.models import Publisher

        r1 = await client.post("/listings", json=_publish_body("eip191-listing-a"))
        r2 = await client.post("/listings", json=_publish_body("eip191-listing-b"))
        assert r1.status_code == 201
        assert r2.status_code == 201

        publishers = db.query(Publisher).all()
        assert len(publishers) == 1
    finally:
        await client.aclose()
        app.dependency_overrides.clear()
