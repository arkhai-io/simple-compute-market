"""
arkhai_e2e_tests/web3_client.py
--------------------------------
Thin factory that returns a connected Web3 instance configured from settings.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from src.settings import settings

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_web3() -> Web3:
    """
    Return a cached Web3 instance connected to the configured RPC endpoint.
    Injects POA middleware automatically (safe to use on both POA and non-POA chains).
    Raises RuntimeError if the connection cannot be established.
    """
    url: str = settings.RPC.URL
    timeout: int = int(settings.get("RPC.TIMEOUT_SECONDS", 30))

    log.info("Connecting to RPC: %s (chain_id=%s)", url, settings.RPC.CHAIN_ID)

    if url.startswith("ws://") or url.startswith("wss://"):
        provider = Web3.WebSocketProvider(url)
    else:
        provider = Web3.HTTPProvider(url, request_kwargs={"timeout": timeout})

    w3 = Web3(provider)

    # POA chains (e.g. Sepolia, BSC, Polygon) include an extra 'extraData' field
    # that exceeds the Ethereum spec.  This middleware handles it transparently.
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    if not w3.is_connected():
        raise RuntimeError(
            f"Cannot connect to RPC endpoint: {url}. "
            "Check RPC.URL in your configuration."
        )

    actual_chain_id = w3.eth.chain_id
    expected_chain_id = int(settings.RPC.CHAIN_ID)
    if actual_chain_id != expected_chain_id:
        raise RuntimeError(
            f"Chain ID mismatch: expected {expected_chain_id}, "
            f"got {actual_chain_id} from {url}"
        )

    log.info("Connected — chain_id=%d, latest block=%d", actual_chain_id, w3.eth.block_number)
    return w3


# Minimal ERC-173 / Ownable ABI — just the functions we need for these tests
OWNABLE_ABI = [
    {
        "inputs": [],
        "name": "owner",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    }
]
