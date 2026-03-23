from __future__ import annotations

import importlib.util
import json
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/bootstrap_local_dev.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_minimal_contracts_fixture(root: Path) -> Path:
    contracts_dir = root / "erc-8004-contracts"
    scripts_dir = contracts_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (contracts_dir / "package.json").write_text(
        json.dumps({"name": "contracts", "scripts": {"local": "npm run local"}}),
        encoding="utf-8",
    )
    (contracts_dir / "hardhat.config.ts").write_text(
        textwrap.dedent(
            """
            export default {
              networks: {
                mainnet: {
                  type: "http",
                  chainType: "l1",
                  url: process.env.MAINNET_RPC_URL || "",
                },
              },
            };
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (scripts_dir / "addresses.ts").write_text(
        textwrap.dedent(
            """
            export const TESTNET_ADDRESSES = {
              identityRegistry: "0x8004A818BFB912233c491871b3d84c89A494BD9e",
              reputationRegistry: "0x8004B663056A597Dffe9eCcC1965A193B7388713",
              validationRegistry: "0x8004Cb1BF31DAf7788923b405b754f57acEB4272",
            } as const;
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return contracts_dir


def test_deploy_local_contracts_uses_reviewable_command_matrix(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_module(SCRIPT_PATH, "bootstrap_local_dev")
    contracts_dir = _write_minimal_contracts_fixture(tmp_path)
    output_path = tmp_path / "local-contracts.json"
    commands: list[tuple[list[str], Path, dict[str, str]]] = []

    def fake_run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
        commands.append(
            (
                command,
                cwd,
                {
                    "LOCALHOST_RPC_URL": env["LOCALHOST_RPC_URL"],
                    "SEPOLIA_RPC_URL": env["SEPOLIA_RPC_URL"],
                    "MAINNET_RPC_URL": env["MAINNET_RPC_URL"],
                },
            )
        )

    monkeypatch.setattr(module, "CONTRACTS_SOURCE_DIR", contracts_dir)
    monkeypatch.setattr(module, "_run_command", fake_run)

    artifact = module.deploy_local_contracts(
        rpc_url="http://127.0.0.1:45165",
        output_path=output_path,
    )

    assert commands == [
        (
            ["npm", "ci", "--legacy-peer-deps"],
            commands[0][1],
            {
                "LOCALHOST_RPC_URL": "http://127.0.0.1:45165",
                "SEPOLIA_RPC_URL": "http://127.0.0.1:45165",
                "MAINNET_RPC_URL": "http://127.0.0.1:45165",
            },
        ),
        (
            ["npx", "hardhat", "run", "scripts/deploy-create2-factory.ts", "--network", "localhost"],
            commands[1][1],
            {
                "LOCALHOST_RPC_URL": "http://127.0.0.1:45165",
                "SEPOLIA_RPC_URL": "http://127.0.0.1:45165",
                "MAINNET_RPC_URL": "http://127.0.0.1:45165",
            },
        ),
        (
            ["npm", "run", "local:fund-owner"],
            commands[2][1],
            {
                "LOCALHOST_RPC_URL": "http://127.0.0.1:45165",
                "SEPOLIA_RPC_URL": "http://127.0.0.1:45165",
                "MAINNET_RPC_URL": "http://127.0.0.1:45165",
            },
        ),
        (
            ["npm", "run", "local:deploy:vanity"],
            commands[3][1],
            {
                "LOCALHOST_RPC_URL": "http://127.0.0.1:45165",
                "SEPOLIA_RPC_URL": "http://127.0.0.1:45165",
                "MAINNET_RPC_URL": "http://127.0.0.1:45165",
            },
        ),
        (
            ["npm", "run", "local:upgrade:vanity:presigned"],
            commands[4][1],
            {
                "LOCALHOST_RPC_URL": "http://127.0.0.1:45165",
                "SEPOLIA_RPC_URL": "http://127.0.0.1:45165",
                "MAINNET_RPC_URL": "http://127.0.0.1:45165",
            },
        ),
        (
            ["npm", "run", "local:verify:vanity"],
            commands[5][1],
            {
                "LOCALHOST_RPC_URL": "http://127.0.0.1:45165",
                "SEPOLIA_RPC_URL": "http://127.0.0.1:45165",
                "MAINNET_RPC_URL": "http://127.0.0.1:45165",
            },
        ),
    ]
    assert output_path.exists()
    assert artifact == json.loads(output_path.read_text(encoding="utf-8"))
    assert artifact["rpc_url"] == "http://127.0.0.1:45165"
    assert artifact["alkahest_address_config_path"] == str(
        ROOT / "core/agent/app/data/alkahest_anvil_addresses.json"
    )
    assert artifact["contracts"] == {
        "IDENTITY_REGISTRY_ADDRESS": "0x8004A818BFB912233c491871b3d84c89A494BD9e",
        "REPUTATION_REGISTRY_ADDRESS": "0x8004B663056A597Dffe9eCcC1965A193B7388713",
        "VALIDATION_REGISTRY_ADDRESS": "0x8004Cb1BF31DAf7788923b405b754f57acEB4272",
    }
    assert artifact["recommended_env"]["CHAIN_NAME"] == "anvil"
    assert artifact["recommended_env"]["CHAIN_RPC_URL"] == "http://127.0.0.1:45165"


def test_prepare_contracts_workspace_injects_dynamic_localhost_network(
    tmp_path: Path,
) -> None:
    module = _load_module(SCRIPT_PATH, "bootstrap_local_dev_workspace")
    contracts_dir = _write_minimal_contracts_fixture(tmp_path)

    workspace = module.prepare_contracts_workspace(contracts_dir, tmp_path / "work")

    hardhat_config = (workspace / "hardhat.config.ts").read_text(encoding="utf-8")
    assert 'localhost: {' in hardhat_config
    assert 'process.env.LOCALHOST_RPC_URL || "http://127.0.0.1:8545"' in hardhat_config


def test_format_local_deploy_command_uses_canonical_wrapper() -> None:
    module = _load_module(SCRIPT_PATH, "bootstrap_local_dev_command")

    assert (
        module.format_local_deploy_command("http://127.0.0.1:45165")
        == "python scripts/deploy_local_contracts.py --rpc-url http://127.0.0.1:45165"
    )
