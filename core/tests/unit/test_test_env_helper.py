from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "core/agent/app/utils/test_env.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_test_env_prints_canonical_local_deploy_guidance(
    monkeypatch,
    capsys,
) -> None:
    module = _load_module(SCRIPT_PATH, "test_env_helper")

    class FakeEnv:
        rpc_url = "http://127.0.0.1:45165"
        mock_addresses = type("MockAddresses", (), {"erc20_a": "0x1111111111111111111111111111111111111111"})()
        god_wallet_provider = object()
        alice = "0x2222222222222222222222222222222222222222"
        bob = "0x3333333333333333333333333333333333333333"

    transfers: list[tuple[str, int]] = []

    class FakeMockERC20:
        def __init__(self, *_args):
            pass

        def transfer(self, recipient: str, amount: int) -> None:
            transfers.append((recipient, amount))

    monkeypatch.setattr(module, "EnvTestManager", FakeEnv)
    monkeypatch.setattr(module, "MockERC20", FakeMockERC20)
    monkeypatch.setattr("builtins.input", lambda: "")

    module.main()

    out = capsys.readouterr().out
    assert transfers == [
        ("0x2222222222222222222222222222222222222222", 90000000000),
        ("0x3333333333333333333333333333333333333333", 90000000000),
    ]
    assert "deploy:anvil" not in out
    assert (
        "python scripts/deploy_local_contracts.py --rpc-url http://127.0.0.1:45165"
        in out
    )
    assert (
        "market dev deploy-contracts --rpc-url http://127.0.0.1:45165"
        in out
    )
    assert (
        f"ALKAHEST_ADDRESS_CONFIG_PATH={ROOT / 'core/agent/app/data/alkahest_anvil_addresses.json'}"
        in out
    )
