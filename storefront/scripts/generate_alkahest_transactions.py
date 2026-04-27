#!/usr/bin/env python3
"""Generate Alkahest transactions file for docker-compose Anvil.

Spins up EnvTestManager (which starts its own Anvil and deploys all Alkahest
contracts + mock ERC-20 tokens), funds Alice and Bob with MOCK tokens, then
records every transaction from every block so docker-compose can replay them
on a fresh Anvil at startup.

Run once from repo root and commit the transactions file:

    cd storefront && uv run python scripts/generate_alkahest_transactions.py

The transactions file is saved to:
    erc-8004-contracts/alkahest-transactions.json

docker-compose contracts-deploy then replays these before deploying ERC-8004.
Regenerate only when the alkahest_py wheel version changes.
"""

from __future__ import annotations

import json
import pathlib
import sys

import requests
from alkahest_py import EnvTestManager, MockERC20

ALICE_FUNDING = 1_000_000_000  # 1B MOCK tokens
BOB_FUNDING = 1_000_000_000

DEFAULT_OUTPUT = (
    pathlib.Path(__file__).parents[3] / "erc-8004-contracts" / "alkahest-transactions.json"
)


def rpc_call(rpc_url: str, method: str, params: list) -> object:
    resp = requests.post(
        rpc_url,
        json={"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()
    if "error" in result:
        raise RuntimeError(f"RPC error {method}: {result['error']}")
    return result["result"]


def collect_transactions(rpc_url: str) -> list[dict]:
    """Iterate all blocks and collect every transaction."""
    latest_hex = rpc_call(rpc_url, "eth_blockNumber", [])
    latest = int(latest_hex, 16)
    print(f"Collecting transactions from blocks 0..{latest}")

    txns = []
    for block_num in range(latest + 1):
        block = rpc_call(rpc_url, "eth_getBlockByNumber", [hex(block_num), True])
        if block is None:
            continue
        for tx in block.get("transactions", []):
            entry: dict = {
                "from": tx["from"],
                "data": tx.get("input", "0x"),
                "value": tx.get("value", "0x0"),
            }
            if tx.get("to"):
                entry["to"] = tx["to"]
            txns.append(entry)

    return txns


def main() -> int:
    print("Starting EnvTestManager (deploys Alkahest contracts on internal Anvil)...")
    env = EnvTestManager()

    rpc_url = env.rpc_url.replace("ws://", "http://").rstrip("/")
    print(f"Internal Anvil RPC: {rpc_url}")

    mock_erc20_addr = env.mock_addresses.erc20_a
    escrow_addr = env.addresses.erc20_addresses.escrow_obligation_nontierable

    print(f"\nAddresses:")
    print(f"  god:   {env.god}")
    print(f"  alice: {env.alice}")
    print(f"  bob:   {env.bob}")
    print(f"  MOCK ERC-20:          {mock_erc20_addr}")
    print(f"  ERC20 escrow (non-t): {escrow_addr}")

    # Fund agents with MOCK tokens
    mock_erc20 = MockERC20(mock_erc20_addr, env.god_wallet_provider)
    print(f"\nMinting {ALICE_FUNDING:,} MOCK → Alice ({env.alice})...")
    mock_erc20.transfer(env.alice, ALICE_FUNDING)
    print(f"Minting {BOB_FUNDING:,} MOCK → Bob ({env.bob})...")
    mock_erc20.transfer(env.bob, BOB_FUNDING)
    print(f"Alice MOCK balance: {mock_erc20.balance_of(env.alice):,}")
    print(f"Bob MOCK balance:   {mock_erc20.balance_of(env.bob):,}")

    # Collect all transactions from blocks
    transactions = collect_transactions(rpc_url)
    print(f"\nCollected {len(transactions)} transactions")

    output = {
        "_comment": "Generated from alkahest_py. Regenerate when wheel version changes.",
        "_mock_erc20": mock_erc20_addr.lower(),
        "_erc20_escrow_nontierable": escrow_addr.lower(),
        "transactions": transactions,
    }

    out_path = DEFAULT_OUTPUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2))
    print(f"Transactions saved: {out_path}")

    print("\nNext steps:")
    print("  1. Commit erc-8004-contracts/alkahest-transactions.json")
    print("  2. docker-compose contracts-deploy replays them before deploying ERC-8004")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
