"""Unit tests for CLI order auth header generation (_get_auth_headers)."""

import pytest

PRIVATE_KEY = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
OWNER_ADDRESS = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"


def test_no_private_key_returns_empty():
    from market_buyer.groups.order import _get_auth_headers
    assert _get_auth_headers("create_order", "http://localhost:8000", None) == {}


def test_empty_private_key_returns_empty():
    from market_buyer.groups.order import _get_auth_headers
    assert _get_auth_headers("create_order", "http://localhost:8000", "") == {}


def test_with_key_returns_headers():
    pytest.importorskip("eth_account")
    from market_buyer.groups.order import _get_auth_headers
    headers = _get_auth_headers("create_order", "http://localhost:8000", PRIVATE_KEY)
    assert "X-Signature" in headers
    assert "X-Timestamp" in headers


def test_timestamp_is_recent():
    import time
    pytest.importorskip("eth_account")
    from market_buyer.groups.order import _get_auth_headers
    before = int(time.time())
    headers = _get_auth_headers("create_order", "http://localhost:8000", PRIVATE_KEY)
    after = int(time.time())
    ts = int(headers["X-Timestamp"])
    assert before <= ts <= after


def test_signature_is_recoverable_create_order():
    eth_account = pytest.importorskip("eth_account")
    messages_mod = pytest.importorskip("eth_account.messages")
    from market_buyer.groups.order import _get_auth_headers
    headers = _get_auth_headers("create_order", "http://localhost:8000", PRIVATE_KEY)
    ts = headers["X-Timestamp"]
    msg = messages_mod.encode_defunct(text=f"create_order:http://localhost:8000:{ts}")
    recovered = eth_account.Account.recover_message(msg, signature=headers["X-Signature"])
    assert recovered.lower() == OWNER_ADDRESS.lower()


def test_signature_is_recoverable_close_order():
    eth_account = pytest.importorskip("eth_account")
    messages_mod = pytest.importorskip("eth_account.messages")
    from market_buyer.groups.order import _get_auth_headers
    headers = _get_auth_headers("close_order", "order-xyz-123", PRIVATE_KEY)
    ts = headers["X-Timestamp"]
    msg = messages_mod.encode_defunct(text=f"close_order:order-xyz-123:{ts}")
    recovered = eth_account.Account.recover_message(msg, signature=headers["X-Signature"])
    assert recovered.lower() == OWNER_ADDRESS.lower()
