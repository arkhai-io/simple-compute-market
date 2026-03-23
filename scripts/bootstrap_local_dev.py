#!/usr/bin/env python3
"""Canonical local bootstrap helpers for the parent repo."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from bootstrap_contract import (  # type: ignore[import-not-found]
    ALKAHEST_ADDRESS_CONFIG_PATH,
    CANONICAL_LOCAL_DEPLOY_WRAPPER,
    CANONICAL_NODE_INSTALL_COMMAND,
)


ROOT = SCRIPT_DIR.parents[0]
CONTRACTS_SOURCE_DIR = ROOT / "erc-8004-contracts"
LOCALHOST_NETWORK_SNIPPET = """\
    localhost: {
      type: "http",
      chainType: "l1",
      url: process.env.LOCALHOST_RPC_URL || "http://127.0.0.1:8545",
    },
"""
LOCAL_UPGRADE_SCRIPT = """\
import hre from "hardhat";
import {
  createWalletClient,
  encodeFunctionData,
  getCreate2Address,
  Hex,
  http,
  keccak256,
} from "viem";
import {
  EXPECTED_OWNER,
  IMPLEMENTATION_SALTS,
  SAFE_SINGLETON_FACTORY,
  getAddresses,
} from "./addresses";

const RPC_URL = process.env.LOCALHOST_RPC_URL || "http://127.0.0.1:8545";

async function rpc(method: string, params: unknown[] = []): Promise<void> {
  const response = await fetch(RPC_URL, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method,
      params,
    }),
  });
  const payload = await response.json();
  if (payload.error) {
    throw new Error(`${method} failed: ${payload.error.message}`);
  }
}

async function main() {
  const { viem } = await hre.network.connect("localhost");
  const publicClient = await viem.getPublicClient();
  const chainId = await publicClient.getChainId();
  const addresses = getAddresses(chainId);

  await rpc("anvil_impersonateAccount", [EXPECTED_OWNER]);

  try {
    const walletClient = createWalletClient({
      account: EXPECTED_OWNER,
      chain: publicClient.chain,
      transport: http(RPC_URL),
    });

    const minimalUUPSArtifact = await hre.artifacts.readArtifact("MinimalUUPS");
    const identityImplArtifact = await hre.artifacts.readArtifact("IdentityRegistryUpgradeable");
    const reputationImplArtifact = await hre.artifacts.readArtifact("ReputationRegistryUpgradeable");
    const validationImplArtifact = await hre.artifacts.readArtifact("ValidationRegistryUpgradeable");

    const identityImpl = getCreate2Address({
      from: SAFE_SINGLETON_FACTORY,
      salt: IMPLEMENTATION_SALTS.identityRegistry,
      bytecodeHash: keccak256(identityImplArtifact.bytecode as Hex),
    });
    const reputationImpl = getCreate2Address({
      from: SAFE_SINGLETON_FACTORY,
      salt: IMPLEMENTATION_SALTS.reputationRegistry,
      bytecodeHash: keccak256(reputationImplArtifact.bytecode as Hex),
    });
    const validationImpl = getCreate2Address({
      from: SAFE_SINGLETON_FACTORY,
      salt: IMPLEMENTATION_SALTS.validationRegistry,
      bytecodeHash: keccak256(validationImplArtifact.bytecode as Hex),
    });

    const implSlot =
      "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc" as const;

    async function upgradeProxy(
      proxyAddress: `0x${string}`,
      expectedImplementation: `0x${string}`,
      initData: `0x${string}`,
    ): Promise<void> {
      const storageValue = await publicClient.getStorageAt({
        address: proxyAddress,
        slot: implSlot,
      });
      const currentImplementation = storageValue
        ? (`0x${storageValue.slice(-40)}` as `0x${string}`)
        : null;
      if (
        currentImplementation &&
        currentImplementation.toLowerCase() === expectedImplementation.toLowerCase()
      ) {
        return;
      }

      const callData = encodeFunctionData({
        abi: minimalUUPSArtifact.abi,
        functionName: "upgradeToAndCall",
        args: [expectedImplementation, initData],
      });

      const hash = await walletClient.sendTransaction({
        account: EXPECTED_OWNER,
        to: proxyAddress,
        data: callData,
      });
      const receipt = await publicClient.waitForTransactionReceipt({ hash });
      if (receipt.status !== "success") {
        throw new Error(`Upgrade failed for ${proxyAddress}`);
      }
    }

    await upgradeProxy(
      addresses.identityRegistry,
      identityImpl,
      encodeFunctionData({
        abi: identityImplArtifact.abi,
        functionName: "initialize",
        args: [],
      }),
    );
    await upgradeProxy(
      addresses.reputationRegistry,
      reputationImpl,
      encodeFunctionData({
        abi: reputationImplArtifact.abi,
        functionName: "initialize",
        args: [addresses.identityRegistry],
      }),
    );
    await upgradeProxy(
      addresses.validationRegistry,
      validationImpl,
      encodeFunctionData({
        abi: validationImplArtifact.abi,
        functionName: "initialize",
        args: [addresses.identityRegistry],
      }),
    );
  } finally {
    await rpc("anvil_stopImpersonatingAccount", [EXPECTED_OWNER]);
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
LOCAL_DEPLOY_COMMANDS: list[list[str]] = [
    ["npx", "hardhat", "run", "scripts/deploy-create2-factory.ts", "--network", "localhost"],
    ["npm", "run", "local:fund-owner"],
    ["npm", "run", "local:deploy:vanity"],
    ["npx", "hardhat", "run", "scripts/local-upgrade-impersonated.ts", "--network", "localhost"],
    ["npm", "run", "local:verify:vanity"],
]


def format_local_deploy_command(rpc_url: str) -> str:
    command = CANONICAL_LOCAL_DEPLOY_WRAPPER[:-1] + [rpc_url]
    return " ".join(command)


def _normalize_http_rpc_url(rpc_url: str) -> str:
    if rpc_url.startswith("ws://"):
        return "http://" + rpc_url[len("ws://") :]
    if rpc_url.startswith("wss://"):
        return "https://" + rpc_url[len("wss://") :]
    return rpc_url


def _assert_contracts_submodule_ready(contracts_dir: Path) -> None:
    required_paths = [
        contracts_dir / "package.json",
        contracts_dir / "hardhat.config.ts",
        contracts_dir / "scripts/addresses.ts",
    ]
    missing = [path for path in required_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "erc-8004-contracts is not initialized. Run "
            "'git submodule update --init --recursive' first. Missing: "
            + ", ".join(str(path.relative_to(ROOT)) for path in missing)
        )


def _copy_contracts_workspace(source_dir: Path, destination_dir: Path) -> None:
    shutil.copytree(
        source_dir,
        destination_dir,
        ignore=shutil.ignore_patterns(".git", "node_modules", "artifacts", "cache"),
    )


def _ensure_localhost_network(hardhat_config_path: Path) -> None:
    text = hardhat_config_path.read_text(encoding="utf-8")
    if "localhost:" in text:
        return
    marker = "    mainnet: {\n"
    if marker in text:
        updated = text.replace(marker, LOCALHOST_NETWORK_SNIPPET + marker, 1)
    else:
        updated = text.replace("  networks: {\n", f"  networks: {{\n{LOCALHOST_NETWORK_SNIPPET}", 1)
    hardhat_config_path.write_text(updated, encoding="utf-8")


def _write_local_upgrade_script(contracts_dir: Path) -> None:
    (contracts_dir / "scripts/local-upgrade-impersonated.ts").write_text(
        LOCAL_UPGRADE_SCRIPT,
        encoding="utf-8",
    )


def prepare_contracts_workspace(source_dir: Path, workspace_root: Path) -> Path:
    destination_dir = workspace_root / source_dir.name
    if destination_dir.exists():
        shutil.rmtree(destination_dir)
    workspace_root.mkdir(parents=True, exist_ok=True)
    _copy_contracts_workspace(source_dir, destination_dir)
    _ensure_localhost_network(destination_dir / "hardhat.config.ts")
    _write_local_upgrade_script(destination_dir)
    return destination_dir


def _command_env(rpc_url: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "LOCALHOST_RPC_URL": rpc_url,
            "SEPOLIA_RPC_URL": rpc_url,
            "MAINNET_RPC_URL": rpc_url,
        }
    )
    return env


def _run_command(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _read_local_contract_addresses(addresses_path: Path) -> dict[str, str]:
    text = addresses_path.read_text(encoding="utf-8")
    match = re.search(
        r'TESTNET_ADDRESSES\s*=\s*\{\s*'
        r'identityRegistry:\s*"(?P<identity>0x[0-9a-fA-F]{40})",\s*'
        r'reputationRegistry:\s*"(?P<reputation>0x[0-9a-fA-F]{40})",\s*'
        r'validationRegistry:\s*"(?P<validation>0x[0-9a-fA-F]{40})"',
        text,
        re.DOTALL,
    )
    if not match:
        raise ValueError(
            "Could not parse TESTNET_ADDRESSES from erc-8004-contracts/scripts/addresses.ts"
        )
    return {
        "IDENTITY_REGISTRY_ADDRESS": match.group("identity"),
        "REPUTATION_REGISTRY_ADDRESS": match.group("reputation"),
        "VALIDATION_REGISTRY_ADDRESS": match.group("validation"),
    }


def build_local_contract_artifact(
    *,
    rpc_url: str,
    addresses_path: Path,
) -> dict[str, Any]:
    contracts = _read_local_contract_addresses(addresses_path)
    alkahest_path = str(ROOT / ALKAHEST_ADDRESS_CONFIG_PATH)
    return {
        "rpc_url": rpc_url,
        "contracts": contracts,
        "alkahest_address_config_path": alkahest_path,
        "recommended_env": {
            "CHAIN_NAME": "anvil",
            "CHAIN_RPC_URL": rpc_url,
            "ALKAHEST_ADDRESS_CONFIG_PATH": alkahest_path,
            **contracts,
        },
        "command_matrix": {
            "install": CANONICAL_NODE_INSTALL_COMMAND,
            "deploy": LOCAL_DEPLOY_COMMANDS,
        },
    }


def deploy_local_contracts(
    *,
    rpc_url: str,
    output_path: Path | None = None,
) -> dict[str, Any]:
    _assert_contracts_submodule_ready(CONTRACTS_SOURCE_DIR)
    normalized_rpc_url = _normalize_http_rpc_url(rpc_url)
    env = _command_env(normalized_rpc_url)

    with tempfile.TemporaryDirectory(prefix="sms-local-contracts-") as temp_dir:
        workspace = prepare_contracts_workspace(
            CONTRACTS_SOURCE_DIR, Path(temp_dir) / "workspace"
        )
        _run_command(CANONICAL_NODE_INSTALL_COMMAND, cwd=workspace, env=env)
        for command in LOCAL_DEPLOY_COMMANDS:
            _run_command(command, cwd=workspace, env=env)
        artifact = build_local_contract_artifact(
            rpc_url=normalized_rpc_url,
            addresses_path=workspace / "scripts/addresses.ts",
        )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return artifact


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    deploy = subparsers.add_parser("deploy-contracts")
    deploy.add_argument("--rpc-url", required=True)
    deploy.add_argument("--output")

    show = subparsers.add_parser("print-contracts-command")
    show.add_argument("--rpc-url", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "deploy-contracts":
        output_path = Path(args.output) if args.output else None
        artifact = deploy_local_contracts(
            rpc_url=args.rpc_url,
            output_path=output_path,
        )
        print(json.dumps(artifact, indent=2, sort_keys=True))
        return 0

    if args.command == "print-contracts-command":
        print(format_local_deploy_command(args.rpc_url))
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
