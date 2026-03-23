#!/usr/bin/env python3
"""Replay Alkahest contract deployment transactions on docker Anvil.

Reads alkahest-transactions.json (committed artifact) and replays every
transaction via eth_sendTransaction, then verifies contract bytecode exists.

Called by contracts-deploy container before npm run deploy:anvil.
Stdlib only — no pip packages required.

Exits 0 on success, non-zero on failure.
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

RPC_URL = "http://anvil:8545"
SCRIPT_DIR = pathlib.Path(__file__).parent
TRANSACTIONS_FILE = SCRIPT_DIR / "alkahest-transactions.json"

# Standard Anvil account #0 (deterministic)
DEPLOYER = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"

# 8M gas — covers the largest Alkahest deployment tx
GAS_LIMIT = "0x7A1200"


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


def get_receipt(tx_hash: str, retries: int = 10, delay: float = 0.5) -> dict:
    """Poll for a receipt — Anvil auto-mines but may need a tick to commit."""
    for _ in range(retries):
        receipt = rpc("eth_getTransactionReceipt", [tx_hash])
        if receipt is not None:
            return receipt
        time.sleep(delay)
    raise RuntimeError(f"Receipt not found after {retries} attempts: {tx_hash}")


def receipt_ok(receipt: dict) -> bool:
    """Return True if the receipt indicates success.

    Handles Anvil returning status as hex string "0x1", integer 1, or missing
    the field entirely (pre-Byzantium / some Anvil nightly builds).
    """
    status = receipt.get("status")
    if status is None:
        # No status field — treat as success if receipt exists
        return True
    if isinstance(status, str):
        return int(status, 16) != 0
    return bool(status)


def wait_for_anvil(retries: int = 30, delay: float = 1.0) -> None:
    print(f"Waiting for Anvil at {RPC_URL}...")
    for i in range(retries):
        try:
            rpc("eth_blockNumber", [])
            print("Anvil is ready.")
            return
        except Exception:
            if i < retries - 1:
                time.sleep(delay)
    raise RuntimeError("Anvil did not become ready in time")


def main() -> int:
    wait_for_anvil()

    # Safety: deployer nonce must be 0 on a fresh Anvil
    nonce_hex = rpc("eth_getTransactionCount", [DEPLOYER, "latest"])
    nonce = int(nonce_hex, 16)
    if nonce != 0:
        print(
            f"ERROR: Deployer {DEPLOYER} has nonce {nonce}, expected 0."
            " Fresh Anvil required."
        )
        return 1

    data = json.loads(TRANSACTIONS_FILE.read_text())
    transactions = data["transactions"]
    mock_erc20 = data["_mock_erc20"]
    escrow_addr = data["_erc20_escrow_nontierable"]

    print(f"Replaying {len(transactions)} Alkahest transactions...")
    for i, tx in enumerate(transactions):
        tx_params: dict = {
            "from": tx["from"],
            "data": tx["data"],
            "value": tx.get("value", "0x0"),
            "gas": GAS_LIMIT,
        }
        if "to" in tx:
            tx_params["to"] = tx["to"]

        tx_hash = rpc("eth_sendTransaction", [tx_params])

        receipt = get_receipt(tx_hash)
        if not receipt_ok(receipt):
            print(f"ERROR: Transaction {i} failed (status={receipt.get('status')}). Hash: {tx_hash}")
            return 1

        if (i + 1) % 10 == 0 or (i + 1) == len(transactions):
            print(f"  [{i + 1}/{len(transactions)}] replayed")

    # Verify bytecode exists at expected addresses
    mock_code = rpc("eth_getCode", [mock_erc20, "latest"])
    if not mock_code or mock_code == "0x":
        print(f"ERROR: No bytecode at MOCK ERC-20 address {mock_erc20}")
        return 1

    escrow_code = rpc("eth_getCode", [escrow_addr, "latest"])
    if not escrow_code or escrow_code == "0x":
        print(f"ERROR: No bytecode at ERC20 escrow address {escrow_addr}")
        return 1

    print("✅ Alkahest deployment complete")
    print(f"   MOCK ERC-20:          {mock_erc20}")
    print(f"   ERC20 escrow (non-t): {escrow_addr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
