from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/check_chain_profile.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("check_chain_profile", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )


def test_load_chain_profile_prefers_shared_rpc_and_local_contracts(tmp_path: Path) -> None:
    module = _load_script_module()
    shared_secrets_dir = tmp_path / "shared"
    local_secrets_dir = tmp_path / "local"
    shared_secrets_dir.mkdir()
    local_secrets_dir.mkdir()

    _write_env(
        shared_secrets_dir / "alchemy.env",
        {
            "ETH_SEPOLIA_HTTP_RPC_URL": "https://eth-sepolia.example/rpc",
        },
    )
    _write_env(
        local_secrets_dir / "shared.env",
        {
            "CHAIN_NAME": "ethereum_sepolia",
            "CHAIN_ID": "11155111",
        },
    )
    _write_env(
        local_secrets_dir / "contracts.env",
        {
            "IDENTITY_REGISTRY_ADDRESS": "0x1111111111111111111111111111111111111111",
            "REPUTATION_REGISTRY_ADDRESS": "0x2222222222222222222222222222222222222222",
            "VALIDATION_REGISTRY_ADDRESS": "0x3333333333333333333333333333333333333333",
        },
    )

    profile = module.load_chain_profile(
        shared_secrets_dir=shared_secrets_dir,
        local_secrets_dir=local_secrets_dir,
    )

    assert profile.chain_name == "ethereum_sepolia"
    assert profile.chain_id == 11155111
    assert profile.rpc_url == "https://eth-sepolia.example/rpc"
    assert profile.token_registry_path == module.ROOT / "core/agent/app/data/token_registry_eth_sepolia.json"
    assert profile.registry_addresses == {
        "IDENTITY_REGISTRY_ADDRESS": "0x1111111111111111111111111111111111111111",
        "REPUTATION_REGISTRY_ADDRESS": "0x2222222222222222222222222222222222222222",
        "VALIDATION_REGISTRY_ADDRESS": "0x3333333333333333333333333333333333333333",
    }


def test_validate_chain_profile_rejects_chain_id_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script_module()
    shared_secrets_dir = tmp_path / "shared"
    local_secrets_dir = tmp_path / "local"
    shared_secrets_dir.mkdir()
    local_secrets_dir.mkdir()

    _write_env(shared_secrets_dir / "alchemy.env", {"ETH_SEPOLIA_HTTP_RPC_URL": "https://eth-sepolia.example/rpc"})
    _write_env(local_secrets_dir / "shared.env", {"CHAIN_NAME": "ethereum_sepolia", "CHAIN_ID": "11155111"})
    _write_env(
        local_secrets_dir / "contracts.env",
        {
            "IDENTITY_REGISTRY_ADDRESS": "0x1111111111111111111111111111111111111111",
            "REPUTATION_REGISTRY_ADDRESS": "0x2222222222222222222222222222222222222222",
            "VALIDATION_REGISTRY_ADDRESS": "0x3333333333333333333333333333333333333333",
        },
    )

    profile = module.load_chain_profile(
        shared_secrets_dir=shared_secrets_dir,
        local_secrets_dir=local_secrets_dir,
    )

    def fake_rpc(url: str, method: str, params: list[object]) -> str:
        assert url == "https://eth-sepolia.example/rpc"
        assert method == "eth_chainId"
        assert params == []
        return hex(1)

    monkeypatch.setattr(module, "_rpc_request", fake_rpc)

    with pytest.raises(SystemExit, match="reported chain id 1, expected 11155111"):
        module.validate_chain_profile(profile)


def test_validate_chain_profile_rejects_missing_bytecode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script_module()
    shared_secrets_dir = tmp_path / "shared"
    local_secrets_dir = tmp_path / "local"
    shared_secrets_dir.mkdir()
    local_secrets_dir.mkdir()

    _write_env(shared_secrets_dir / "alchemy.env", {"ETH_SEPOLIA_HTTP_RPC_URL": "https://eth-sepolia.example/rpc"})
    _write_env(local_secrets_dir / "shared.env", {"CHAIN_NAME": "ethereum_sepolia", "CHAIN_ID": "11155111"})
    _write_env(
        local_secrets_dir / "contracts.env",
        {
            "IDENTITY_REGISTRY_ADDRESS": "0x1111111111111111111111111111111111111111",
            "REPUTATION_REGISTRY_ADDRESS": "0x2222222222222222222222222222222222222222",
            "VALIDATION_REGISTRY_ADDRESS": "0x3333333333333333333333333333333333333333",
        },
    )

    profile = module.load_chain_profile(
        shared_secrets_dir=shared_secrets_dir,
        local_secrets_dir=local_secrets_dir,
    )

    bytecode = {
        "0x1111111111111111111111111111111111111111": "0x6000",
        "0x2222222222222222222222222222222222222222": "0x6001",
        "0x3333333333333333333333333333333333333333": "0x",
    }

    def fake_rpc(url: str, method: str, params: list[object]) -> str:
        if method == "eth_chainId":
            return hex(11155111)
        assert method == "eth_getCode"
        return bytecode[params[0]]

    monkeypatch.setattr(module, "_rpc_request", fake_rpc)

    with pytest.raises(SystemExit, match="VALIDATION_REGISTRY_ADDRESS has no bytecode"):
        module.validate_chain_profile(profile)


def test_validate_chain_profile_accepts_matching_chain_and_deployed_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script_module()
    shared_secrets_dir = tmp_path / "shared"
    local_secrets_dir = tmp_path / "local"
    shared_secrets_dir.mkdir()
    local_secrets_dir.mkdir()

    _write_env(shared_secrets_dir / "alchemy.env", {"ETH_SEPOLIA_HTTP_RPC_URL": "https://eth-sepolia.example/rpc"})
    _write_env(local_secrets_dir / "shared.env", {"CHAIN_NAME": "ethereum_sepolia", "CHAIN_ID": "11155111"})
    _write_env(
        local_secrets_dir / "contracts.env",
        {
            "IDENTITY_REGISTRY_ADDRESS": "0x1111111111111111111111111111111111111111",
            "REPUTATION_REGISTRY_ADDRESS": "0x2222222222222222222222222222222222222222",
            "VALIDATION_REGISTRY_ADDRESS": "0x3333333333333333333333333333333333333333",
        },
    )

    profile = module.load_chain_profile(
        shared_secrets_dir=shared_secrets_dir,
        local_secrets_dir=local_secrets_dir,
    )

    def fake_rpc(url: str, method: str, params: list[object]) -> str:
        if method == "eth_chainId":
            return hex(11155111)
        assert method == "eth_getCode"
        return "0x60006000"

    monkeypatch.setattr(module, "_rpc_request", fake_rpc)

    results = module.validate_chain_profile(profile)

    assert results["chain_id"] == 11155111
    assert results["contracts"] == {
        "IDENTITY_REGISTRY_ADDRESS": "0x1111111111111111111111111111111111111111",
        "REPUTATION_REGISTRY_ADDRESS": "0x2222222222222222222222222222222222222222",
        "VALIDATION_REGISTRY_ADDRESS": "0x3333333333333333333333333333333333333333",
    }
