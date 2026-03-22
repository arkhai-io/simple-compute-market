#!/usr/bin/env python3
"""Create an isolated local sandbox for human buyer CLI testing."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHARED_SECRETS_DIR = Path("~/.config/web3-ops").expanduser()
DEFAULT_LOCAL_SECRETS_DIR = Path("~/.config/simple-market-service").expanduser()
DEFAULT_SANDBOX_ROOT = Path("/tmp")
DEFAULT_REGISTRY_URL = "http://127.0.0.1:28080/"
DEFAULT_PROVISIONING_URL = "http://127.0.0.1:28081/"
DEFAULT_BUYER_AGENT_URL = "http://127.0.0.1:28001/"
DEFAULT_SELLER_AGENT_URL = "http://127.0.0.1:28002/"


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value.strip().strip("'").strip('"')
    return values


def _optional_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return _parse_env_file(path)


def _load_merged_env_file(
    filename: str,
    *,
    shared_secrets_dir: Path,
    local_secrets_dir: Path,
) -> dict[str, str]:
    return {
        **_optional_env_file(shared_secrets_dir / filename),
        **_optional_env_file(local_secrets_dir / filename),
    }


def _require_keys(values: dict[str, str], *, label: str, keys: tuple[str, ...]) -> None:
    missing = sorted(key for key in keys if not values.get(key))
    if missing:
        raise SystemExit(f"Missing required {label} keys: {', '.join(missing)}")


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )


def build_human_buyer_context(
    *,
    shared_secrets_dir: Path,
    local_secrets_dir: Path,
    sandbox_dir: Path,
    registry_url: str = DEFAULT_REGISTRY_URL,
    provisioning_url: str = DEFAULT_PROVISIONING_URL,
    buyer_agent_url: str = DEFAULT_BUYER_AGENT_URL,
    seller_agent_url: str = DEFAULT_SELLER_AGENT_URL,
) -> dict[str, dict[str, str] | str]:
    wallets = _load_merged_env_file(
        "wallets.env",
        shared_secrets_dir=shared_secrets_dir,
        local_secrets_dir=local_secrets_dir,
    )
    buyer_overrides = _parse_env_file(local_secrets_dir / "buyer-agent.env")
    seller_overrides = _parse_env_file(local_secrets_dir / "seller-agent.env")
    canary_env = _parse_env_file(local_secrets_dir / "prod-canary.env")

    _require_keys(
        wallets,
        label="wallets.env",
        keys=("BUYER_PRIVATE_KEY", "SELLER_PRIVATE_KEY"),
    )
    _require_keys(
        buyer_overrides,
        label="buyer-agent.env",
        keys=("BASE_URL_OVERRIDE",),
    )
    _require_keys(
        seller_overrides,
        label="seller-agent.env",
        keys=("BASE_URL_OVERRIDE",),
    )
    _require_keys(
        canary_env,
        label="prod-canary.env",
        keys=("SELLER_AGENT_ID", "BUYER_AGENT_ID", "SSH_PRIVATE_KEY_PATH"),
    )

    return {
        "buyer_env": {
            "AGENT_URL": buyer_agent_url,
            "AGENT_AUTH_URL": buyer_overrides["BASE_URL_OVERRIDE"],
            "REGISTRY_URL": registry_url,
            "AGENT_PRIV_KEY": wallets["BUYER_PRIVATE_KEY"],
        },
        "seller_env": {
            "AGENT_URL": seller_agent_url,
            "AGENT_AUTH_URL": seller_overrides["BASE_URL_OVERRIDE"],
            "REGISTRY_URL": registry_url,
            "AGENT_PRIV_KEY": wallets["SELLER_PRIVATE_KEY"],
        },
        "context": {
            "sandbox_dir": str(sandbox_dir),
            "market_binary": str(sandbox_dir / "venv/bin/market"),
            "registry_url": registry_url,
            "provisioning_url": provisioning_url,
            "buyer_agent_url": buyer_agent_url,
            "seller_agent_url": seller_agent_url,
            "buyer_agent_id": canary_env["BUYER_AGENT_ID"],
            "seller_agent_id": canary_env["SELLER_AGENT_ID"],
            "ssh_private_key_path": canary_env["SSH_PRIVATE_KEY_PATH"],
        },
    }


def _run_command(command: list[str], cwd: Path) -> None:
    print(f"[run] ({cwd}) {' '.join(command)}")
    subprocess.run(command, cwd=cwd, check=True)


def build_install_plan(*, sandbox_dir: Path) -> list[list[str]]:
    dist_dir = sandbox_dir / "dist"
    venv_dir = sandbox_dir / "venv"
    return [
        ["uv", "build", "--wheel", "--out-dir", str(dist_dir), str(ROOT / "cli")],
        ["uv", "venv", "--python", "3.12", str(venv_dir)],
    ]


def _find_built_wheel(dist_dir: Path) -> Path:
    wheels = sorted(dist_dir.glob("market_cli-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"Expected exactly one market_cli wheel in {dist_dir}, found {len(wheels)}")
    return wheels[0]


def setup_human_buyer_sandbox(
    *,
    shared_secrets_dir: Path,
    local_secrets_dir: Path,
    sandbox_dir: Path,
    registry_url: str = DEFAULT_REGISTRY_URL,
    provisioning_url: str = DEFAULT_PROVISIONING_URL,
    buyer_agent_url: str = DEFAULT_BUYER_AGENT_URL,
    seller_agent_url: str = DEFAULT_SELLER_AGENT_URL,
) -> dict[str, str]:
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    context = build_human_buyer_context(
        shared_secrets_dir=shared_secrets_dir,
        local_secrets_dir=local_secrets_dir,
        sandbox_dir=sandbox_dir,
        registry_url=registry_url,
        provisioning_url=provisioning_url,
        buyer_agent_url=buyer_agent_url,
        seller_agent_url=seller_agent_url,
    )

    _write_env_file(sandbox_dir / "buyer.env", context["buyer_env"])
    _write_env_file(sandbox_dir / "seller.env", context["seller_env"])
    context_path = sandbox_dir / "context.json"
    context_path.write_text(json.dumps(context["context"], indent=2) + "\n", encoding="utf-8")

    for command in build_install_plan(sandbox_dir=sandbox_dir):
        _run_command(command, cwd=ROOT)

    wheel_path = _find_built_wheel(sandbox_dir / "dist")
    install_command = [
        "uv",
        "pip",
        "install",
        "--python",
        str(sandbox_dir / "venv/bin/python"),
        str(wheel_path),
    ]
    _run_command(install_command, cwd=ROOT)

    return {
        "sandbox_dir": str(sandbox_dir),
        "buyer_env_path": str(sandbox_dir / "buyer.env"),
        "seller_env_path": str(sandbox_dir / "seller.env"),
        "context_path": str(context_path),
        "market_binary": str(sandbox_dir / "venv/bin/market"),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build the local market CLI into an isolated sandbox and render the "
            "buyer/seller env bundle used for human live testing."
        )
    )
    parser.add_argument("--shared-secrets-dir", type=Path, default=DEFAULT_SHARED_SECRETS_DIR)
    parser.add_argument("--local-secrets-dir", type=Path, default=DEFAULT_LOCAL_SECRETS_DIR)
    parser.add_argument("--sandbox-dir", type=Path)
    parser.add_argument("--registry-url", default=DEFAULT_REGISTRY_URL)
    parser.add_argument("--provisioning-url", default=DEFAULT_PROVISIONING_URL)
    parser.add_argument("--buyer-agent-url", default=DEFAULT_BUYER_AGENT_URL)
    parser.add_argument("--seller-agent-url", default=DEFAULT_SELLER_AGENT_URL)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    sandbox_dir = args.sandbox_dir
    if sandbox_dir is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        sandbox_dir = DEFAULT_SANDBOX_ROOT / f"market-buyer-sandbox-{timestamp}"

    result = setup_human_buyer_sandbox(
        shared_secrets_dir=args.shared_secrets_dir.expanduser(),
        local_secrets_dir=args.local_secrets_dir.expanduser(),
        sandbox_dir=sandbox_dir.expanduser(),
        registry_url=args.registry_url,
        provisioning_url=args.provisioning_url,
        buyer_agent_url=args.buyer_agent_url,
        seller_agent_url=args.seller_agent_url,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
