#!/usr/bin/env python3
"""
Deploy Alkahest and ERC-8004 contracts to a temporary Anvil instance
and dump the chain state for use in a pre-deployed Docker image.

Runs during Docker build (see agent/anvil.dockerfile).

Steps:
  1. EnvTestManager() → spawns Anvil on random port + deploys Alkahest contracts
  2. Fund alice/bob with 90B mock ERC20 tokens
  3. Deploy ERC-8004 registries via Hardhat (Identity, Reputation, Validation)
  4. Dump chain state via `cast rpc anvil_dumpState`
  5. Write /build/anvil-state/state.json and /build/anvil-state/addresses.json
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from alkahest_py import EnvTestManager, MockERC20


def main() -> None:
    output_dir = Path("/build/anvil-state")
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. Spin up Anvil + deploy Alkahest contracts ──────────────────
    print("=== Starting Anvil and deploying Alkahest contracts ===")
    env = EnvTestManager()

    # ── 2. Fund test accounts ─────────────────────────────────────────
    print("Funding alice and bob with 90B mock ERC20 tokens...")
    mock_erc20 = MockERC20(env.mock_addresses.erc20_a, env.god_wallet_provider)
    mock_erc20.transfer(env.alice, 90_000_000_000)
    mock_erc20.transfer(env.bob, 90_000_000_000)

    # ── 3. Extract the random port from EnvTestManager ────────────────
    port = int(env.rpc_url.split(":")[2].split("/")[0])
    rpc_url = f"http://localhost:{port}"
    print(f"Anvil running on {rpc_url}")

    # ── 4. Deploy ERC-8004 registries via Hardhat ─────────────────────
    print("\n=== Deploying ERC-8004 registry contracts ===")
    hardhat_env = {**os.environ, "ANVIL_RPC_URL": rpc_url}
    result = subprocess.run(
        [
            "npx", "hardhat", "run",
            "scripts/deploy-upgradeable.ts",
            "--network", "anvil",
        ],
        cwd="/build/erc-8004-contracts",
        env=hardhat_env,
        capture_output=True,
        text=True,
        check=True,
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    # ── 5. Parse ERC-8004 proxy addresses from Hardhat output ─────────
    erc8004_addresses: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "IdentityRegistry Proxy:" in line:
            erc8004_addresses["identity_registry"] = line.split(":")[-1].strip()
        elif "ReputationRegistry Proxy:" in line:
            erc8004_addresses["reputation_registry"] = line.split(":")[-1].strip()
        elif "ValidationRegistry Proxy:" in line:
            erc8004_addresses["validation_registry"] = line.split(":")[-1].strip()

    if len(erc8004_addresses) != 3:
        print(
            f"ERROR: Expected 3 ERC-8004 addresses, got {len(erc8004_addresses)}: "
            f"{erc8004_addresses}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"ERC-8004 addresses: {json.dumps(erc8004_addresses, indent=2)}")

    # ── 6. Dump chain state ───────────────────────────────────────────
    print("\n=== Dumping chain state ===")
    dump_result = subprocess.run(
        ["cast", "rpc", "anvil_dumpState", "--rpc-url", rpc_url],
        capture_output=True,
        text=True,
        check=True,
    )
    state_hex = dump_result.stdout.strip()
    # cast rpc returns a JSON-encoded hex string (e.g. "0x7b22...")
    if state_hex.startswith('"') and state_hex.endswith('"'):
        state_hex = state_hex[1:-1]

    # The hex encodes the JSON state object that `anvil --load-state` expects.
    state_bytes = bytes.fromhex(state_hex.removeprefix("0x"))
    (output_dir / "state.json").write_bytes(state_bytes)
    print(f"State dumped ({len(state_bytes)} bytes)")

    # ── 7. Write addresses.json ───────────────────────────────────────
    addresses = {
        "alkahest": {
            "trusted_oracle_arbiter": str(
                env.addresses.arbiters_addresses.trusted_oracle_arbiter
            ),
            "mock_erc20": str(env.mock_addresses.erc20_a),
        },
        "erc8004": erc8004_addresses,
        "accounts": {
            "alice": str(env.alice),
            "bob": str(env.bob),
        },
        "rpc_url": "http://localhost:8545",
    }
    (output_dir / "addresses.json").write_text(json.dumps(addresses, indent=2) + "\n")
    print(f"\nAddresses written to {output_dir / 'addresses.json'}:")
    print(json.dumps(addresses, indent=2))

    print("\n=== Done! ===")


if __name__ == "__main__":
    main()
