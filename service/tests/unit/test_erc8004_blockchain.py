"""Unit tests for service.clients.erc8004.blockchain (pure functions, no mocking needed)."""
from service.clients.erc8004.blockchain import (
    rpc_url_for_http_provider,
    build_erc8004_canonical_id,
)


def test_rpc_url_ws_to_http():
    assert rpc_url_for_http_provider("ws://localhost:8545") == "http://localhost:8545"


def test_rpc_url_wss_to_https():
    assert rpc_url_for_http_provider("wss://mainnet.infura.io/ws/v3/abc") == "https://mainnet.infura.io/v3/abc"


def test_rpc_url_http_unchanged():
    assert rpc_url_for_http_provider("http://localhost:8545") == "http://localhost:8545"


def test_rpc_url_empty():
    assert rpc_url_for_http_provider("") == ""


def test_build_erc8004_canonical_id():
    cid = build_erc8004_canonical_id(1337, "0xABCDEF1234567890ABCDEF1234567890ABCDEF12", 42)
    assert cid == "eip155:1337:0xabcdef1234567890abcdef1234567890abcdef12:42"


def test_build_erc8004_canonical_id_lowercase():
    cid = build_erc8004_canonical_id(1, "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", 0)
    assert cid.startswith("eip155:1:")
    assert cid == cid.lower() or "eip155" in cid
