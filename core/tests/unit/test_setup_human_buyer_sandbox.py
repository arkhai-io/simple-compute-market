from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/setup_human_buyer_sandbox.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("setup_human_buyer_sandbox", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )


def test_build_human_buyer_context_uses_local_auth_urls_and_shared_wallets(tmp_path: Path) -> None:
    module = _load_script_module()
    shared_secrets_dir = tmp_path / "shared"
    local_secrets_dir = tmp_path / "local"
    sandbox_dir = tmp_path / "sandbox"
    shared_secrets_dir.mkdir()
    local_secrets_dir.mkdir()

    _write_env(
        shared_secrets_dir / "wallets.env",
        {
            "BUYER_PRIVATE_KEY": "0xbuyer",
            "SELLER_PRIVATE_KEY": "0xseller",
        },
    )
    _write_env(
        local_secrets_dir / "buyer-agent.env",
        {"BASE_URL_OVERRIDE": "http://10.243.0.117:8000/"},
    )
    _write_env(
        local_secrets_dir / "seller-agent.env",
        {"BASE_URL_OVERRIDE": "http://10.243.0.68:8000/"},
    )
    _write_env(
        local_secrets_dir / "prod-canary.env",
        {
            "SELLER_AGENT_ID": "seller-id",
            "BUYER_AGENT_ID": "buyer-id",
            "SSH_PRIVATE_KEY_PATH": "/tmp/tenant-key",
        },
    )

    context = module.build_human_buyer_context(
        shared_secrets_dir=shared_secrets_dir,
        local_secrets_dir=local_secrets_dir,
        sandbox_dir=sandbox_dir,
    )

    assert context["buyer_env"]["AGENT_URL"] == "http://127.0.0.1:28001/"
    assert context["buyer_env"]["AGENT_AUTH_URL"] == "http://10.243.0.117:8000/"
    assert context["buyer_env"]["REGISTRY_URL"] == "http://127.0.0.1:28080/"
    assert context["buyer_env"]["AGENT_PRIV_KEY"] == "0xbuyer"
    assert context["seller_env"]["AGENT_AUTH_URL"] == "http://10.243.0.68:8000/"
    assert context["context"]["seller_agent_id"] == "seller-id"
    assert context["context"]["buyer_agent_id"] == "buyer-id"
    assert context["context"]["ssh_private_key_path"] == "/tmp/tenant-key"
    assert context["context"]["market_binary"] == str(sandbox_dir / "venv/bin/market")


def test_setup_human_buyer_sandbox_writes_bundle_and_runs_install_plan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script_module()
    shared_secrets_dir = tmp_path / "shared"
    local_secrets_dir = tmp_path / "local"
    sandbox_dir = tmp_path / "sandbox"
    shared_secrets_dir.mkdir()
    local_secrets_dir.mkdir()

    _write_env(
        shared_secrets_dir / "wallets.env",
        {
            "BUYER_PRIVATE_KEY": "0xbuyer",
            "SELLER_PRIVATE_KEY": "0xseller",
        },
    )
    _write_env(local_secrets_dir / "buyer-agent.env", {"BASE_URL_OVERRIDE": "http://10.243.0.117:8000/"})
    _write_env(local_secrets_dir / "seller-agent.env", {"BASE_URL_OVERRIDE": "http://10.243.0.68:8000/"})
    _write_env(
        local_secrets_dir / "prod-canary.env",
        {
            "SELLER_AGENT_ID": "seller-id",
            "BUYER_AGENT_ID": "buyer-id",
            "SSH_PRIVATE_KEY_PATH": "/tmp/tenant-key",
        },
    )

    commands: list[list[str]] = []
    monkeypatch.setattr(module, "_run_command", lambda command, cwd: commands.append(command))
    monkeypatch.setattr(
        module,
        "_find_built_wheel",
        lambda dist_dir: dist_dir / "market_cli-0.1.0-py3-none-any.whl",
    )

    result = module.setup_human_buyer_sandbox(
        shared_secrets_dir=shared_secrets_dir,
        local_secrets_dir=local_secrets_dir,
        sandbox_dir=sandbox_dir,
    )

    assert commands == [
        [
            "uv",
            "build",
            "--wheel",
            "--out-dir",
            str(sandbox_dir / "dist"),
            str(module.ROOT / "cli"),
        ],
        ["uv", "venv", "--python", "3.12", str(sandbox_dir / "venv")],
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(sandbox_dir / "venv/bin/python"),
            str(sandbox_dir / "dist/market_cli-0.1.0-py3-none-any.whl"),
        ],
    ]
    buyer_env = (sandbox_dir / "buyer.env").read_text(encoding="utf-8")
    seller_env = (sandbox_dir / "seller.env").read_text(encoding="utf-8")
    context = json.loads((sandbox_dir / "context.json").read_text(encoding="utf-8"))

    assert "AGENT_URL=http://127.0.0.1:28001/" in buyer_env
    assert "AGENT_AUTH_URL=http://10.243.0.117:8000/" in buyer_env
    assert "AGENT_URL=http://127.0.0.1:28002/" in seller_env
    assert context["sandbox_dir"] == str(sandbox_dir)
    assert result["context_path"] == str(sandbox_dir / "context.json")
