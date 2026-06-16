from __future__ import annotations

import pytest

from tests.e2e.roles.scenarios.vms.escrow_helper import _ensure_ws_rpc_url


@pytest.mark.parametrize(
    ("input_url", "expected"),
    [
        ("ws://anvil:8545", "ws://anvil:8545"),
        ("wss://example.invalid/ws", "wss://example.invalid/ws"),
        ("http://anvil:8545", "ws://anvil:8545"),
        ("https://example.invalid/rpc", "wss://example.invalid/rpc"),
        ("  http://localhost:8545  ", "ws://localhost:8545"),
    ],
)
def test_ensure_ws_rpc_url_accepts_or_coerces_supported_urls(input_url, expected):
    assert _ensure_ws_rpc_url(input_url) == expected


@pytest.mark.parametrize("input_url", ["", "   ", "ftp://example.invalid", "localhost:8545"])
def test_ensure_ws_rpc_url_rejects_unsupported_urls(input_url):
    with pytest.raises(ValueError, match="rpc_url|unsupported scheme"):
        _ensure_ws_rpc_url(input_url)
