#!/usr/bin/env python3
"""Materialize host-local env bundles from shared and project-local secrets.

This script keeps the source-of-truth local and out of Git, then renders the
runtime files under /etc/simple-market-service with the derived values that are
easy to drift.

By default, shared credentials live under ~/.config/web3-ops and project-
specific overlays live under ~/.config/simple-market-service:

- shared Alchemy HTTP/WSS RPC endpoints
- shared wallet and SSH credentials
- project-local contracts/env overrides
- provisioning SSH_PRIVATE_KEY and MANAGEMENT_VARS_YAML base64 payloads
- seller/buyer wallet injection for agent and canary env files
"""

from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHARED_SECRETS_DIR = Path("~/.config/web3-ops").expanduser()
LOCAL_SECRETS_DIR = Path("~/.config/simple-market-service").expanduser()
OUTPUT_DIR = Path("/etc/simple-market-service")
AGENT_TEMPLATE = ROOT / "core/agent/.env.production.sample"
PROVISIONING_TEMPLATE = ROOT / "async-provisioning-service/.env.production.sample"
REGISTRY_TEMPLATE = ROOT / "erc-8004-registry-py/.env.sample"
REQUIRED_SHARED_OR_LOCAL_FILES = (
    "alchemy.env",
    "wallets.env",
)
REQUIRED_LOCAL_FILES = (
    "buyer-agent.env",
    "contracts.env",
    "prod-canary.env",
    "provisioning.env",
    "registry.env",
    "seller-agent.env",
    "shared.env",
)
CHAIN_CONFIG = {
    "base_sepolia": {
        "chain_id": "84532",
        "http_key": "ALCHEMY_BASE_SEPOLIA_HTTP_URL",
        "wss_key": "ALCHEMY_BASE_SEPOLIA_WSS_URL",
        "token_registry_path": "/app/core/agent/app/data/token_registry_base_sepolia.json",
    },
    "base": {
        "chain_id": "8453",
        "http_key": "ALCHEMY_BASE_MAINNET_HTTP_URL",
        "wss_key": "ALCHEMY_BASE_MAINNET_WSS_URL",
        "token_registry_path": "/app/core/agent/app/data/token_registry_base_sepolia.json",
    },
    "ethereum_sepolia": {
        "chain_id": "11155111",
        "http_key": "ETH_SEPOLIA_HTTP_RPC_URL",
        "wss_key": "ETH_SEPOLIA_WSS_RPC_URL",
        "token_registry_path": "/app/core/agent/app/data/token_registry_eth_sepolia.json",
    },
}


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = _strip_matching_quotes(value.strip())
    return values


def _strip_matching_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _quote_if_needed(value: str) -> str:
    if any(char.isspace() for char in value) or value.startswith('"') or value.endswith('"'):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    lines = [f"{key}={_quote_if_needed(str(value))}" for key, value in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _write_text_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    os.chmod(path, 0o600)


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


def _ensure_required_files(*, local_secrets_dir: Path, shared_secrets_dir: Path) -> None:
    missing_local = sorted(
        filename for filename in REQUIRED_LOCAL_FILES if not (local_secrets_dir / filename).exists()
    )
    missing_shared_or_local = sorted(
        filename
        for filename in REQUIRED_SHARED_OR_LOCAL_FILES
        if not (shared_secrets_dir / filename).exists() and not (local_secrets_dir / filename).exists()
    )
    if missing_local or missing_shared_or_local:
        messages: list[str] = []
        if missing_local:
            messages.append(f"Missing required local secret files: {', '.join(missing_local)}")
        if missing_shared_or_local:
            messages.append(
                "Missing required shared or local secret files: "
                + ", ".join(missing_shared_or_local)
            )
        raise SystemExit("; ".join(messages))


def _require_keys(values: dict[str, str], *, label: str, keys: tuple[str, ...]) -> None:
    missing = sorted(key for key in keys if not values.get(key))
    if missing:
        raise SystemExit(f"Missing required {label} keys: {', '.join(missing)}")


def _chain_context(shared: dict[str, str], alchemy: dict[str, str]) -> tuple[str, str, str, str, str]:
    chain_name = shared.get("CHAIN_NAME", "base_sepolia")
    if chain_name not in CHAIN_CONFIG:
        raise SystemExit(
            "shared.env:CHAIN_NAME must be one of "
            + ", ".join(sorted(CHAIN_CONFIG))
            + f", got {chain_name}"
        )
    chain_config = CHAIN_CONFIG[chain_name]
    http_url = alchemy.get(chain_config["http_key"], "")
    wss_url = alchemy.get(chain_config["wss_key"], "")
    if not http_url or not wss_url:
        raise SystemExit(
            "alchemy.env is missing required RPC URLs for "
            f"{chain_name}: {chain_config['http_key']}, {chain_config['wss_key']}"
        )
    return (
        chain_name,
        shared.get("CHAIN_ID", chain_config["chain_id"]),
        http_url,
        wss_url,
        chain_config["token_registry_path"],
    )


def _load_templates() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    return (
        _parse_env_file(AGENT_TEMPLATE),
        _parse_env_file(PROVISIONING_TEMPLATE),
        _parse_env_file(REGISTRY_TEMPLATE),
    )


def _base64_file(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def materialize_host_envs(
    *,
    shared_secrets_dir: Path = SHARED_SECRETS_DIR,
    local_secrets_dir: Path,
    output_dir: Path,
) -> list[Path]:
    _ensure_required_files(local_secrets_dir=local_secrets_dir, shared_secrets_dir=shared_secrets_dir)

    shared = _parse_env_file(local_secrets_dir / "shared.env")
    alchemy = _load_merged_env_file(
        "alchemy.env",
        shared_secrets_dir=shared_secrets_dir,
        local_secrets_dir=local_secrets_dir,
    )
    contracts = _parse_env_file(local_secrets_dir / "contracts.env")
    wallets = _load_merged_env_file(
        "wallets.env",
        shared_secrets_dir=shared_secrets_dir,
        local_secrets_dir=local_secrets_dir,
    )
    registry_overrides = _parse_env_file(local_secrets_dir / "registry.env")
    provisioning_overrides = _parse_env_file(local_secrets_dir / "provisioning.env")
    seller_overrides = _parse_env_file(local_secrets_dir / "seller-agent.env")
    buyer_overrides = _parse_env_file(local_secrets_dir / "buyer-agent.env")
    canary_overrides = _parse_env_file(local_secrets_dir / "prod-canary.env")

    _require_keys(
        shared,
        label="shared.env",
        keys=(
            "CHAIN_NAME",
            "ZEROTIER_NETWORK",
            "FRP_SERVER_ADDR",
            "FRP_DOMAIN",
            "FRP_DASHBOARD_PASSWORD",
            "DEFAULT_VM_HOST",
            "REGISTRY_URL",
            "PROVISIONING_SERVICE_URL",
        ),
    )
    _require_keys(
        contracts,
        label="contracts.env",
        keys=(
            "IDENTITY_REGISTRY_ADDRESS",
            "REPUTATION_REGISTRY_ADDRESS",
            "VALIDATION_REGISTRY_ADDRESS",
        ),
    )
    _require_keys(
        wallets,
        label="wallets.env",
        keys=(
            "SELLER_PRIVATE_KEY",
            "SELLER_WALLET_ADDRESS",
            "BUYER_PRIVATE_KEY",
            "BUYER_WALLET_ADDRESS",
            "SSH_PUBLIC_KEY",
            "PROVISIONER_SSH_PRIVATE_KEY_PATH",
            "CANARY_TENANT_SSH_PRIVATE_KEY_PATH",
        ),
    )
    _require_keys(
        provisioning_overrides,
        label="provisioning.env",
        keys=("DATABASE_URL", "REDIS_URL", "REDIS_QUEUE_NAME", "ANSIBLE_BECOME_PASS"),
    )
    _require_keys(registry_overrides, label="registry.env", keys=("DATABASE_URL",))
    _require_keys(seller_overrides, label="seller-agent.env", keys=("AGENT_ID", "GEMINI_API_KEY"))
    _require_keys(buyer_overrides, label="buyer-agent.env", keys=("AGENT_ID", "GEMINI_API_KEY"))
    _require_keys(
        canary_overrides,
        label="prod-canary.env",
        keys=("SELLER_AGENT_URL", "BUYER_AGENT_URL", "SELLER_AGENT_ID", "BUYER_AGENT_ID"),
    )

    chain_name, chain_id, http_url, wss_url, token_registry_path = _chain_context(shared, alchemy)
    management_vars_path = Path(
        provisioning_overrides.get("MANAGEMENT_VARS_PATH", str(local_secrets_dir / "management-vars.yaml"))
    ).expanduser()
    if not management_vars_path.exists():
        raise SystemExit(f"Missing management-vars file: {management_vars_path}")

    provisioner_key_path = Path(wallets["PROVISIONER_SSH_PRIVATE_KEY_PATH"]).expanduser()
    if not provisioner_key_path.exists():
        raise SystemExit(f"Missing provisioner SSH key: {provisioner_key_path}")

    tenant_key_path = Path(wallets["CANARY_TENANT_SSH_PRIVATE_KEY_PATH"]).expanduser()
    if not tenant_key_path.exists():
        raise SystemExit(f"Missing tenant SSH key: {tenant_key_path}")

    agent_template, provisioning_template, registry_template = _load_templates()

    contracts_env = {
        "CHAIN_NAME": chain_name,
        "CHAIN_ID": chain_id,
        "RPC_URL": http_url,
        **contracts,
    }

    registry_env = {
        **registry_template,
        **registry_overrides,
        "CHAIN_ID": chain_id,
        "RPC_URL": http_url,
        **contracts,
    }

    provisioning_env = {
        **provisioning_template,
        **provisioning_overrides,
        "CHAIN_NAME": chain_name,
        "ZEROTIER_NETWORK": shared["ZEROTIER_NETWORK"],
        "DEFAULT_VM_HOST": shared["DEFAULT_VM_HOST"],
        "REGISTRY_URL": shared["REGISTRY_URL"],
        "FRP_SERVER_ADDR": shared["FRP_SERVER_ADDR"],
        "FRP_DOMAIN": shared["FRP_DOMAIN"],
        "FRP_DASHBOARD_PASSWORD": shared["FRP_DASHBOARD_PASSWORD"],
        "SSH_PRIVATE_KEY": _base64_file(provisioner_key_path),
        "MANAGEMENT_VARS_YAML": _base64_file(management_vars_path),
    }
    provisioning_env.pop("MANAGEMENT_VARS_PATH", None)

    common_agent_env = {
        "CHAIN_NAME": chain_name,
        "CHAIN_ID": chain_id,
        "REGISTRY_URL": shared["REGISTRY_URL"],
        "CHAIN_RPC_URL": wss_url,
        "TOKEN_REGISTRY_PATH": token_registry_path,
        "SSH_PUBLIC_KEY": wallets["SSH_PUBLIC_KEY"],
        "ZEROTIER_NETWORK": shared["ZEROTIER_NETWORK"],
        "PROVISIONING_SERVICE_URL": shared["PROVISIONING_SERVICE_URL"],
        "DEFAULT_VM_HOST": shared["DEFAULT_VM_HOST"],
        "FRP_SERVER_ADDR": shared["FRP_SERVER_ADDR"],
        "FRP_DOMAIN": shared["FRP_DOMAIN"],
        "FRP_DASHBOARD_PASSWORD": shared["FRP_DASHBOARD_PASSWORD"],
        **contracts,
    }
    seller_agent_env = {
        **agent_template,
        **common_agent_env,
        **seller_overrides,
        "AGENT_PRIV_KEY": wallets["SELLER_PRIVATE_KEY"],
        "AGENT_WALLET_ADDRESS": wallets["SELLER_WALLET_ADDRESS"],
    }
    buyer_agent_env = {
        **agent_template,
        **common_agent_env,
        **buyer_overrides,
        "AGENT_PRIV_KEY": wallets["BUYER_PRIVATE_KEY"],
        "AGENT_WALLET_ADDRESS": wallets["BUYER_WALLET_ADDRESS"],
    }

    canary_env = {
        "CHAIN_NAME": chain_name,
        "CHAIN_ID": chain_id,
        "CHAIN_RPC_URL": http_url,
        "REGISTRY_URL": shared["REGISTRY_URL"],
        "PROVISIONING_SERVICE_URL": shared["PROVISIONING_SERVICE_URL"],
        "FRP_DASHBOARD_URL": f"http://{shared['FRP_SERVER_ADDR']}:7500",
        "FRP_DASHBOARD_PASSWORD": shared["FRP_DASHBOARD_PASSWORD"],
        "SSH_PRIVATE_KEY_PATH": str(tenant_key_path),
        "SELLER_PRIVATE_KEY": wallets["SELLER_PRIVATE_KEY"],
        "BUYER_PRIVATE_KEY": wallets["BUYER_PRIVATE_KEY"],
        **canary_overrides,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    written_paths = [
        output_dir / "contracts.env",
        output_dir / "registry.env",
        output_dir / "provisioning.env",
        output_dir / "seller-agent.env",
        output_dir / "buyer-agent.env",
        output_dir / "prod-canary.env",
        output_dir / "management-vars.yaml",
    ]
    _write_env_file(output_dir / "contracts.env", contracts_env)
    _write_env_file(output_dir / "registry.env", registry_env)
    _write_env_file(output_dir / "provisioning.env", provisioning_env)
    _write_env_file(output_dir / "seller-agent.env", seller_agent_env)
    _write_env_file(output_dir / "buyer-agent.env", buyer_agent_env)
    _write_env_file(output_dir / "prod-canary.env", canary_env)
    _write_text_file(output_dir / "management-vars.yaml", management_vars_path.read_text(encoding="utf-8"))
    return written_paths


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Render /etc/simple-market-service env bundles from shared "
            "~/.config/web3-ops credentials plus project-local "
            "~/.config/simple-market-service overlays"
        )
    )
    parser.add_argument(
        "--shared-secrets-dir",
        type=Path,
        default=SHARED_SECRETS_DIR,
        help="Directory containing shared alchemy.env and wallets.env credentials.",
    )
    parser.add_argument(
        "--local-secrets-dir",
        type=Path,
        default=LOCAL_SECRETS_DIR,
        help="Directory containing project-local shared.env and role-specific overlay fragments.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Destination directory for rendered host-local env files.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    written = materialize_host_envs(
        shared_secrets_dir=args.shared_secrets_dir.expanduser(),
        local_secrets_dir=args.local_secrets_dir.expanduser(),
        output_dir=args.output_dir.expanduser(),
    )
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
