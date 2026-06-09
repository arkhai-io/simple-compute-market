"""Pluggable-identity Phase 2 — middleware dispatch + back-compat tests.

These tests exercise the storefront's seller_auth and buyer_auth middlewares
against the four-header signed-request wire shape and the back-compat path
where ``X-Identity-Scheme`` / ``X-Identity`` are absent.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient

from market_storefront.middleware import buyer_auth, seller_auth

pytestmark = pytest.mark.asyncio

PRIVATE_KEY = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
OWNER_ADDRESS = "0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc"  # lowercase form

OTHER_PRIVATE_KEY = "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a"


def _sign(message: str, key: str = PRIVATE_KEY) -> str:
    from eth_account import Account
    from eth_account.messages import encode_defunct

    return Account.sign_message(
        encode_defunct(text=message), key
    ).signature.hex()


# ---------------------------------------------------------------------------
# Seller auth — single configured wallet
# ---------------------------------------------------------------------------


def _seller_app() -> FastAPI:
    app = FastAPI()

    @app.post("/op/{listing_id}")
    async def _op(
        listing_id: str,
        request: Request,
        _: None = Depends(seller_auth.make_seller_auth_dep("close_listing")),
    ) -> dict:
        return {"ok": True}

    return app


async def _post_seller(
    app: FastAPI, listing_id: str, headers: dict[str, str]
) -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.post(f"/op/{listing_id}", json={}, headers=headers)


async def _call_seller(headers: dict[str, str]):
    from tests._settings_overrides import settings_overrides

    with settings_overrides(**{"wallet.address": OWNER_ADDRESS}):
        return await _post_seller(_seller_app(), "listing-1", headers)


async def test_seller_auth_passes_with_full_header_set():
    ts = str(int(time.time()))
    sig = _sign(f"close_listing:listing-1:{ts}")
    resp = await _call_seller({
        "X-Signature": sig,
        "X-Timestamp": ts,
        "X-Identity-Scheme": "eip191",
        "X-Identity": OWNER_ADDRESS,
    })
    assert resp.status_code == 200


async def test_seller_auth_passes_without_identity_headers_back_compat():
    """Pre-pluggable clients (no X-Identity headers) still work."""
    ts = str(int(time.time()))
    sig = _sign(f"close_listing:listing-1:{ts}")
    resp = await _call_seller({"X-Signature": sig, "X-Timestamp": ts})
    assert resp.status_code == 200


async def test_seller_auth_rejects_mismatched_identity():
    """Client claims a different identity than the configured wallet → 403."""
    ts = str(int(time.time()))
    sig = _sign(f"close_listing:listing-1:{ts}")
    resp = await _call_seller({
        "X-Signature": sig,
        "X-Timestamp": ts,
        "X-Identity-Scheme": "eip191",
        "X-Identity": "0xdeadbeef00000000000000000000000000000000",
    })
    assert resp.status_code == 403


async def test_seller_auth_rejects_unknown_scheme():
    """Unknown scheme → 403 (scheme mismatch)."""
    ts = str(int(time.time()))
    sig = _sign(f"close_listing:listing-1:{ts}")
    resp = await _call_seller({
        "X-Signature": sig,
        "X-Timestamp": ts,
        "X-Identity-Scheme": "not-a-real-scheme",
        "X-Identity": OWNER_ADDRESS,
    })
    # The scheme-mismatch check fires before the verifier lookup, so this
    # returns 403 rather than 400. Either is acceptable per the design;
    # asserting the actual behavior.
    assert resp.status_code == 403


async def test_seller_auth_rejects_wrong_signature():
    """Valid identity but signature signed by a different key → 403."""
    ts = str(int(time.time()))
    sig = _sign(f"close_listing:listing-1:{ts}", OTHER_PRIVATE_KEY)
    resp = await _call_seller({
        "X-Signature": sig,
        "X-Timestamp": ts,
        "X-Identity-Scheme": "eip191",
        "X-Identity": OWNER_ADDRESS,
    })
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Buyer auth — claimed via body
# ---------------------------------------------------------------------------


async def test_buyer_auth_accepts_matching_x_identity():
    """X-Identity matches body.buyer_address → passes."""
    from market_core.storefront.models.negotiation_models import NegotiateNewRequest

    ts = str(int(time.time()))
    sig = _sign(f"negotiate_new:listing-1:{ts}")

    # Build a request manually since buyer_auth is structurally complex
    body = NegotiateNewRequest(
        listing_id="listing-1",
        buyer_address=OWNER_ADDRESS,
        provision_terms={"duration_seconds": 1, "ssh_public_key": ""},
        proposal={
            "chain_name": "anvil",
            "escrow_address": "0x" + "0" * 40,
            "fields": {"amount": 1, "token": "0x" + "0" * 40},
            "expiration_unix": int(time.time()) + 60,
        },
    )

    # Stub Request — we only need .headers
    class _FakeReq:
        headers = {
            "X-Signature": sig,
            "X-Timestamp": ts,
            "X-Identity-Scheme": "eip191",
            "X-Identity": OWNER_ADDRESS,
        }

    # Should not raise
    buyer_auth.negotiate_new_auth(body, _FakeReq())  # type: ignore[arg-type]


async def test_buyer_auth_rejects_x_identity_mismatching_buyer_address():
    """If X-Identity disagrees with body.buyer_address, reject."""
    from market_core.storefront.models.negotiation_models import NegotiateNewRequest

    ts = str(int(time.time()))
    sig = _sign(f"negotiate_new:listing-1:{ts}")
    body = NegotiateNewRequest(
        listing_id="listing-1",
        buyer_address=OWNER_ADDRESS,  # body says owner
        provision_terms={"duration_seconds": 1, "ssh_public_key": ""},
        proposal={
            "chain_name": "anvil",
            "escrow_address": "0x" + "0" * 40,
            "fields": {"amount": 1, "token": "0x" + "0" * 40},
            "expiration_unix": int(time.time()) + 60,
        },
    )

    class _FakeReq:
        headers = {
            "X-Signature": sig,
            "X-Timestamp": ts,
            "X-Identity-Scheme": "eip191",
            "X-Identity": "0xdeadbeef00000000000000000000000000000000",  # disagrees
        }

    with pytest.raises(HTTPException) as exc_info:
        buyer_auth.negotiate_new_auth(body, _FakeReq())  # type: ignore[arg-type]
    assert exc_info.value.status_code == 403


async def test_buyer_auth_back_compat_no_identity_headers():
    """No X-Identity headers → falls back to body.buyer_address (existing shape)."""
    from market_core.storefront.models.negotiation_models import NegotiateNewRequest

    ts = str(int(time.time()))
    sig = _sign(f"negotiate_new:listing-1:{ts}")
    body = NegotiateNewRequest(
        listing_id="listing-1",
        buyer_address=OWNER_ADDRESS,
        provision_terms={"duration_seconds": 1, "ssh_public_key": ""},
        proposal={
            "chain_name": "anvil",
            "escrow_address": "0x" + "0" * 40,
            "fields": {"amount": 1, "token": "0x" + "0" * 40},
            "expiration_unix": int(time.time()) + 60,
        },
    )

    class _FakeReq:
        headers = {"X-Signature": sig, "X-Timestamp": ts}

    # Should not raise
    buyer_auth.negotiate_new_auth(body, _FakeReq())  # type: ignore[arg-type]
