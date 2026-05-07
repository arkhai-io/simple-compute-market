#!/usr/bin/env python3
"""Register a sentinel agent on the ERC-8004 IdentityRegistry.

Runs after Alkahest and ERC-8004 contracts are deployed (called from
deploy-local.sh) to bake at least one on-chain agent registration into
the Anvil state snapshot.

When the registry service starts against this baked state, its
sync_from_start() replays the Registered event emitted here and creates
the corresponding agent row automatically — making the
test_at_least_one_agent_registered smoke test reliable without any
registry API calls at build time.

Account selection
-----------------
Anvil account #3 is used deliberately:
  #0  0xf39F...2266 — contract deployer (used in deploy_alkahest.py)
  #1  0x7099...79C8 — Alice / buyer agent
  #2  0x3C44...3BC  — Bob / seller agent
  #3  0x90F7...906  — sentinel (this script) — unrelated to market agents

Function selector
-----------------
register(string agentURI) -> keccak256("register(string)")[:4] = 0xf2c298be

The selector is a stable constant derived from the canonical ABI signature.
It is hardcoded here rather than read from Hardhat artifact JSON because:
  - Hardhat's methodIdentifiers field is empty in the artifact structure
    produced by this image's compile step.
  - The selector is deterministic and will not change unless the contract
    interface changes (at which point this script needs updating anyway).
  - Stdlib only — no pip packages required.

Exits 0 on success, non-zero on failure.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

RPC_URL = "http://anvil:8545"

# Anvil account #3 — deterministic test key, NOT used by any market agent
SENTINEL_ADDRESS = "0x90F79bf6EB2c4f870365E785982E1f101E93b906"

# keccak256("register(string)")[:4]  — verified against deployed contract ABI
# ABI source: erc-8004-contracts/abis/IdentityRegistry.json
REGISTER_STRING_SELECTOR = bytes.fromhex("f2c298be")

GAS_LIMIT = "0x100000"  # 1M gas — register() costs ~80k

TOKEN_URI = "https://sentinel.arkhai.test/agent.json"


# ---------------------------------------------------------------------------
# Minimal ABI encoding helpers (stdlib only)
# ---------------------------------------------------------------------------

def _pad32_right(data: bytes) -> bytes:
    """Right-pad bytes to the next 32-byte boundary."""
    remainder = len(data) % 32
    return data if remainder == 0 else data + b"\x00" * (32 - remainder)


def _uint256(n: int) -> bytes:
    return n.to_bytes(32, "big")


def build_calldata(token_uri: str) -> str:
    """ABI-encode register(string agentURI) calldata.

    ABI layout for register(string):
      bytes  0-3:   selector (4 bytes)
      bytes  4-35:  offset to string data = 32 (one slot for the offset itself)
      bytes 36-67:  string byte length
      bytes 68+:    string bytes, right-padded to 32-byte boundary
    """
    uri_bytes = token_uri.encode("utf-8")
    data = (
        REGISTER_STRING_SELECTOR
        + _uint256(32)              # offset: string data starts 32 bytes in
        + _uint256(len(uri_bytes))  # string length
        + _pad32_right(uri_bytes)   # string content
    )
    return "0x" + data.hex()


# ---------------------------------------------------------------------------
# RPC helpers
# ---------------------------------------------------------------------------

def rpc(method: str, params: list) -> object:
    payload = json.dumps(
        {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    ).encode()
    req = urllib.request.Request(
        RPC_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    if "error" in result:
        raise RuntimeError(f"RPC error {method}: {result['error']}")
    return result["result"]


def get_receipt(tx_hash: str, retries: int = 20, delay: float = 0.5) -> dict:
    for _ in range(retries):
        receipt = rpc("eth_getTransactionReceipt", [tx_hash])
        if receipt is not None:
            return receipt
        time.sleep(delay)
    raise RuntimeError(f"Receipt not found after {retries} attempts: {tx_hash}")


def receipt_ok(receipt: dict) -> bool:
    status = receipt.get("status")
    if status is None:
        return True
    return (int(status, 16) != 0) if isinstance(status, str) else bool(status)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    identity_registry = os.environ.get("IDENTITY_REGISTRY_ADDRESS", "").strip()
    if not identity_registry:
        print("ERROR: IDENTITY_REGISTRY_ADDRESS env var not set")
        return 1

    print(f"Seeding sentinel agent on IdentityRegistry {identity_registry}...")
    print(f"  Account : {SENTINEL_ADDRESS} (Anvil #3 — unrelated to market agents)")
    print(f"  TokenURI: {TOKEN_URI}")

    calldata = build_calldata(TOKEN_URI)
    nonce_hex = rpc("eth_getTransactionCount", [SENTINEL_ADDRESS, "latest"])

    tx_hash = rpc("eth_sendTransaction", [{
        "from": SENTINEL_ADDRESS,
        "to": identity_registry,
        "data": calldata,
        "gas": GAS_LIMIT,
        "nonce": nonce_hex,
    }])
    print(f"  tx: {tx_hash}")

    receipt = get_receipt(tx_hash)
    if not receipt_ok(receipt):
        print(f"ERROR: register() transaction reverted. Receipt: {receipt}")
        return 1

    print(f"✅ Sentinel agent registered (block {receipt.get('blockNumber')})")
    print("   registry-service will discover this agent via sync_from_start()")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())