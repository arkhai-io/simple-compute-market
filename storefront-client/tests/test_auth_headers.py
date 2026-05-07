"""Unit tests for the EIP-191 auth-header construction in the SDK.

The SDK's ``_build_auth_headers`` always signs (callers gate on
``private_key is None``); the no-key short-circuit lives on the client
classes and is exercised through their public surface.
"""

import pytest

from storefront_client import _build_auth_headers
from storefront_client.client import SyncStorefrontClient

PRIVATE_KEY = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
OWNER_ADDRESS = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"


def test_build_auth_headers_returns_signature_and_timestamp():
    headers = _build_auth_headers(PRIVATE_KEY, "create_listing", "http://localhost:8000")
    assert "X-Signature" in headers
    assert "X-Timestamp" in headers


def test_build_auth_headers_timestamp_is_recent():
    import time
    before = int(time.time())
    headers = _build_auth_headers(PRIVATE_KEY, "create_listing", "http://localhost:8000")
    after = int(time.time())
    ts = int(headers["X-Timestamp"])
    assert before <= ts <= after


def test_build_auth_headers_signature_recovers_owner_for_create_listing():
    eth_account = pytest.importorskip("eth_account")
    messages_mod = pytest.importorskip("eth_account.messages")
    headers = _build_auth_headers(PRIVATE_KEY, "create_listing", "http://localhost:8000")
    ts = headers["X-Timestamp"]
    msg = messages_mod.encode_defunct(text=f"create_listing:http://localhost:8000:{ts}")
    recovered = eth_account.Account.recover_message(msg, signature=headers["X-Signature"])
    assert recovered.lower() == OWNER_ADDRESS.lower()


def test_build_auth_headers_signature_recovers_owner_for_close_listing():
    eth_account = pytest.importorskip("eth_account")
    messages_mod = pytest.importorskip("eth_account.messages")
    headers = _build_auth_headers(PRIVATE_KEY, "close_listing", "order-xyz-123")
    ts = headers["X-Timestamp"]
    msg = messages_mod.encode_defunct(text=f"close_listing:order-xyz-123:{ts}")
    recovered = eth_account.Account.recover_message(msg, signature=headers["X-Signature"])
    assert recovered.lower() == OWNER_ADDRESS.lower()


def test_client_omits_auth_headers_when_no_private_key():
    """Without a private_key, the client returns an empty header dict
    rather than signing junk; callers rely on the storefront accepting
    unsigned requests when AGENT_WALLET_ADDRESS is unset."""
    client = SyncStorefrontClient("http://test", private_key=None)
    try:
        assert client._auth_headers("create_listing", "0xWallet") == {}
    finally:
        client.close()


def test_client_omits_auth_headers_when_empty_private_key():
    client = SyncStorefrontClient("http://test", private_key="")
    try:
        assert client._auth_headers("create_listing", "0xWallet") == {}
    finally:
        client.close()


def test_client_signs_when_private_key_present():
    client = SyncStorefrontClient("http://test", private_key=PRIVATE_KEY)
    try:
        headers = client._auth_headers("create_listing", "0xWallet")
        assert "X-Signature" in headers
        assert "X-Timestamp" in headers
    finally:
        client.close()
