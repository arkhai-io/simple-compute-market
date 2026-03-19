#!/usr/bin/env python3
"""Validate a production-style deployment env bundle before a canary run."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY_PATH = ROOT / "compute-provisioning-iac/ansible/inventory/hosts"
LOCAL_ONLY_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal"}
PLACEHOLDER_RE = re.compile(r"<[^>]+>")
EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
PRIVATE_KEY_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
AGENT_ID_RE = re.compile(r"^eip155:(?P<chain_id>\d+):(?P<registry>0x[0-9a-fA-F]{40}):(?P<token_id>\d+)$")

AGENT_REQUIRED_KEYS = {
    "GEMINI_API_KEY",
    "BASE_URL_OVERRIDE",
    "PORT",
    "AGENT_ID",
    "AUTO_REGISTER",
    "IDENTITY_REGISTRY_ADDRESS",
    "REPUTATION_REGISTRY_ADDRESS",
    "VALIDATION_REGISTRY_ADDRESS",
    "REGISTRY_URL",
    "CHAIN_RPC_URL",
    "AGENT_PRIV_KEY",
    "AGENT_WALLET_ADDRESS",
    "CHAIN_NAME",
    "SSH_PUBLIC_KEY",
    "ZEROTIER_NETWORK",
    "PROVISIONING_MODE",
    "PROVISIONING_SERVICE_URL",
    "DEFAULT_VM_HOST",
    "FRP_SERVER_ADDR",
    "FRP_DOMAIN",
    "FRP_DASHBOARD_PASSWORD",
}

PROVISIONING_REQUIRED_KEYS = {
    "DATABASE_URL",
    "REDIS_URL",
    "REDIS_QUEUE_NAME",
    "ANSIBLE_TIMEOUT_SECONDS",
    "DEFAULT_VM_HOST",
    "ANSIBLE_BECOME_PASS",
    "ZEROTIER_NETWORK",
    "ENABLE_AUTH",
    "AUTH_FAIL_OPEN",
    "REGISTRY_URL",
    "REGISTRY_CACHE_TTL_SECONDS",
    "REGISTRY_CACHE_MAX_SIZE",
    "ENABLE_RATE_LIMITING",
    "RATE_LIMIT_REQUESTS_PER_MINUTE",
    "FRP_SERVER_ADDR",
    "FRP_DOMAIN",
    "FRP_DASHBOARD_PASSWORD",
    "SSH_PRIVATE_KEY",
    "MANAGEMENT_VARS_YAML",
}

REGISTRY_REQUIRED_KEYS = {
    "DATABASE_URL",
    "CHAIN_ID",
    "RPC_URL",
    "IDENTITY_REGISTRY_ADDRESS",
    "REPUTATION_REGISTRY_ADDRESS",
    "VALIDATION_REGISTRY_ADDRESS",
    "PORT",
    "HOST",
    "ZEROTIER_NETWORK",
}


def _parse_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def _parse_inventory_hosts(path: Path) -> set[str]:
    aliases: set[str] = set()
    section: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
            continue
        if section:
            aliases.add(stripped.split()[0])
    return aliases


def _normalize_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _is_placeholder(value: str, *, allow_zerotier_ip: bool = False) -> bool:
    normalized = _normalize_env_value(value)
    if not normalized:
        return True
    if PLACEHOLDER_RE.search(normalized):
        return True
    if "..." in normalized:
        return True
    if allow_zerotier_ip:
        without_zt = normalized.replace("{ZEROTIER_IP}", "100.64.0.1")
        return _is_placeholder(without_zt, allow_zerotier_ip=False)
    return False


def _validate_required_keys(
    env: dict[str, str], required_keys: set[str], label: str, errors: list[str]
) -> None:
    missing = sorted(required_keys - env.keys())
    if missing:
        errors.append(f"{label}: missing required keys: {', '.join(missing)}")


def _validate_url(
    *,
    value: str,
    label: str,
    errors: list[str],
    allow_zerotier_ip: bool = False,
    allow_local_host: bool = False,
) -> None:
    normalized = _normalize_env_value(value)
    parse_target = normalized
    if allow_zerotier_ip:
        parse_target = parse_target.replace("{ZEROTIER_IP}", "100.64.0.1")
    if _is_placeholder(normalized, allow_zerotier_ip=allow_zerotier_ip):
        errors.append(f"{label}: placeholder value is not allowed: {value}")
        return

    parsed = urlparse(parse_target)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        errors.append(f"{label}: invalid URL: {value}")
        return
    if not allow_local_host and parsed.hostname in LOCAL_ONLY_HOSTS:
        errors.append(f"{label}: local-only host is not allowed: {value}")


def _validate_database_url(value: str, label: str, errors: list[str]) -> None:
    normalized = _normalize_env_value(value)
    if _is_placeholder(normalized):
        errors.append(f"{label}: placeholder value is not allowed: {value}")
        return
    if normalized.startswith("sqlite"):
        errors.append(f"{label}: sqlite is not allowed for deployed canaries: {value}")


def _validate_zerotier_network(value: str, label: str, errors: list[str]) -> None:
    normalized = _normalize_env_value(value)
    if _is_placeholder(normalized):
        errors.append(f"{label}: placeholder value is not allowed: {value}")
        return
    if not re.fullmatch(r"[0-9a-fA-F]{16}", normalized):
        errors.append(f"{label}: expected a 16-hex ZeroTier network id, got: {value}")


def _validate_evm_address(value: str, label: str, errors: list[str]) -> None:
    normalized = _normalize_env_value(value)
    if not EVM_ADDRESS_RE.fullmatch(normalized):
        errors.append(f"{label}: invalid EVM address: {value}")
        return
    if normalized.lower() == "0x" + ("0" * 40):
        errors.append(f"{label}: zero address is not allowed")


def _validate_private_key(value: str, label: str, errors: list[str]) -> None:
    normalized = _normalize_env_value(value)
    if not PRIVATE_KEY_RE.fullmatch(normalized):
        errors.append(f"{label}: invalid hex private key")


def _validate_agent_id(
    value: str, label: str, expected_chain_id: int, expected_registry: str, errors: list[str]
) -> None:
    normalized = _normalize_env_value(value)
    match = AGENT_ID_RE.fullmatch(normalized)
    if not match:
        errors.append(f"{label}: expected canonical agent id, got: {value}")
        return
    if int(match.group("chain_id")) != expected_chain_id:
        errors.append(
            f"{label}: chain id {match.group('chain_id')} does not match expected {expected_chain_id}"
        )
    if match.group("registry").lower() != expected_registry.lower():
        errors.append(
            f"{label}: identity registry {match.group('registry')} does not match expected "
            f"{expected_registry}"
        )


def _validate_ssh_public_key(value: str, label: str, errors: list[str]) -> None:
    normalized = _normalize_env_value(value)
    if _is_placeholder(normalized):
        errors.append(f"{label}: placeholder value is not allowed: {value}")
        return
    if not normalized.startswith(("ssh-ed25519 ", "ssh-rsa ", "ecdsa-sha2-")):
        errors.append(f"{label}: expected an SSH public key, got: {value}")


def _validate_non_empty_secret(value: str, label: str, errors: list[str]) -> None:
    if _is_placeholder(value):
        errors.append(f"{label}: placeholder or empty value is not allowed")


def _compare_equal(left: str, left_label: str, right: str, right_label: str, errors: list[str]) -> None:
    if _normalize_env_value(left) != _normalize_env_value(right):
        errors.append(
            f"{left_label} must match {right_label}: {left_label}={left!r}, {right_label}={right!r}"
        )


def _validate_bundle(
    *,
    agent_env: dict[str, str],
    provisioning_env: dict[str, str],
    registry_env: dict[str, str],
    inventory_hosts: set[str],
    expected_chain_name: str,
    expected_chain_id: int,
    seller_agent_url: str | None,
    buyer_agent_url: str | None,
    seller_agent_id: str | None,
    buyer_agent_id: str | None,
    seller_private_key: str | None,
    buyer_private_key: str | None,
    ssh_private_key_path: str | None,
) -> list[str]:
    errors: list[str] = []

    _validate_required_keys(agent_env, AGENT_REQUIRED_KEYS, "agent env", errors)
    _validate_required_keys(
        provisioning_env, PROVISIONING_REQUIRED_KEYS, "provisioning env", errors
    )
    _validate_required_keys(registry_env, REGISTRY_REQUIRED_KEYS, "registry env", errors)

    if errors:
        return errors

    inventory_hosts = set(inventory_hosts)

    _validate_non_empty_secret(agent_env["GEMINI_API_KEY"], "agent env:GEMINI_API_KEY", errors)
    _validate_url(
        value=agent_env["BASE_URL_OVERRIDE"],
        label="agent env:BASE_URL_OVERRIDE",
        errors=errors,
        allow_zerotier_ip=True,
    )
    _validate_url(
        value=agent_env["REGISTRY_URL"],
        label="agent env:REGISTRY_URL",
        errors=errors,
    )
    _validate_url(
        value=agent_env["PROVISIONING_SERVICE_URL"],
        label="agent env:PROVISIONING_SERVICE_URL",
        errors=errors,
    )
    _validate_url(
        value=agent_env["CHAIN_RPC_URL"],
        label="agent env:CHAIN_RPC_URL",
        errors=errors,
        allow_local_host=True,
    )
    _validate_private_key(agent_env["AGENT_PRIV_KEY"], "agent env:AGENT_PRIV_KEY", errors)
    _validate_evm_address(
        agent_env["AGENT_WALLET_ADDRESS"], "agent env:AGENT_WALLET_ADDRESS", errors
    )
    _validate_ssh_public_key(agent_env["SSH_PUBLIC_KEY"], "agent env:SSH_PUBLIC_KEY", errors)
    _validate_zerotier_network(
        agent_env["ZEROTIER_NETWORK"], "agent env:ZEROTIER_NETWORK", errors
    )
    if _normalize_env_value(agent_env["CHAIN_NAME"]) != expected_chain_name:
        errors.append(
            f"agent env:CHAIN_NAME must be {expected_chain_name}, got {agent_env['CHAIN_NAME']}"
        )
    if _normalize_env_value(agent_env["PROVISIONING_MODE"]) != "http":
        errors.append(
            f"agent env:PROVISIONING_MODE must be http, got {agent_env['PROVISIONING_MODE']}"
        )
    if _normalize_env_value(agent_env["AUTO_REGISTER"]).lower() != "true":
        errors.append("agent env:AUTO_REGISTER must be true for deployed canaries")

    for key in (
        "IDENTITY_REGISTRY_ADDRESS",
        "REPUTATION_REGISTRY_ADDRESS",
        "VALIDATION_REGISTRY_ADDRESS",
    ):
        _validate_evm_address(agent_env[key], f"agent env:{key}", errors)
        _validate_evm_address(registry_env[key], f"registry env:{key}", errors)
        _compare_equal(agent_env[key], f"agent env:{key}", registry_env[key], f"registry env:{key}", errors)

    _validate_database_url(
        provisioning_env["DATABASE_URL"], "provisioning env:DATABASE_URL", errors
    )
    _validate_non_empty_secret(
        provisioning_env["REDIS_URL"], "provisioning env:REDIS_URL", errors
    )
    _validate_zerotier_network(
        provisioning_env["ZEROTIER_NETWORK"], "provisioning env:ZEROTIER_NETWORK", errors
    )
    _validate_url(
        value=provisioning_env["REGISTRY_URL"],
        label="provisioning env:REGISTRY_URL",
        errors=errors,
    )
    _validate_non_empty_secret(
        provisioning_env["ANSIBLE_BECOME_PASS"],
        "provisioning env:ANSIBLE_BECOME_PASS",
        errors,
    )
    _validate_non_empty_secret(
        provisioning_env["FRP_DASHBOARD_PASSWORD"],
        "provisioning env:FRP_DASHBOARD_PASSWORD",
        errors,
    )
    _validate_non_empty_secret(
        provisioning_env["SSH_PRIVATE_KEY"],
        "provisioning env:SSH_PRIVATE_KEY",
        errors,
    )
    _validate_non_empty_secret(
        provisioning_env["MANAGEMENT_VARS_YAML"],
        "provisioning env:MANAGEMENT_VARS_YAML",
        errors,
    )
    if _normalize_env_value(provisioning_env["ENABLE_AUTH"]).lower() != "true":
        errors.append("provisioning env:ENABLE_AUTH must be true")
    if _normalize_env_value(provisioning_env["AUTH_FAIL_OPEN"]).lower() != "false":
        errors.append("provisioning env:AUTH_FAIL_OPEN must be false")

    _validate_database_url(registry_env["DATABASE_URL"], "registry env:DATABASE_URL", errors)
    _validate_url(
        value=registry_env["RPC_URL"],
        label="registry env:RPC_URL",
        errors=errors,
        allow_local_host=True,
    )
    _validate_zerotier_network(
        registry_env["ZEROTIER_NETWORK"], "registry env:ZEROTIER_NETWORK", errors
    )
    try:
        chain_id = int(_normalize_env_value(registry_env["CHAIN_ID"]))
    except ValueError:
        errors.append(f"registry env:CHAIN_ID must be an integer, got {registry_env['CHAIN_ID']}")
    else:
        if chain_id != expected_chain_id:
            errors.append(
                f"registry env:CHAIN_ID must be {expected_chain_id}, got {registry_env['CHAIN_ID']}"
            )

    default_vm_host = _normalize_env_value(agent_env["DEFAULT_VM_HOST"])
    if default_vm_host not in inventory_hosts:
        errors.append(f"agent env:DEFAULT_VM_HOST is not in inventory: {default_vm_host}")
    if _normalize_env_value(provisioning_env["DEFAULT_VM_HOST"]) not in inventory_hosts:
        errors.append(
            "provisioning env:DEFAULT_VM_HOST is not in inventory: "
            f"{provisioning_env['DEFAULT_VM_HOST']}"
        )
    _compare_equal(
        agent_env["DEFAULT_VM_HOST"],
        "agent env:DEFAULT_VM_HOST",
        provisioning_env["DEFAULT_VM_HOST"],
        "provisioning env:DEFAULT_VM_HOST",
        errors,
    )
    _compare_equal(
        agent_env["ZEROTIER_NETWORK"],
        "agent env:ZEROTIER_NETWORK",
        provisioning_env["ZEROTIER_NETWORK"],
        "provisioning env:ZEROTIER_NETWORK",
        errors,
    )
    _compare_equal(
        agent_env["ZEROTIER_NETWORK"],
        "agent env:ZEROTIER_NETWORK",
        registry_env["ZEROTIER_NETWORK"],
        "registry env:ZEROTIER_NETWORK",
        errors,
    )
    _compare_equal(
        agent_env["REGISTRY_URL"],
        "agent env:REGISTRY_URL",
        provisioning_env["REGISTRY_URL"],
        "provisioning env:REGISTRY_URL",
        errors,
    )

    for label, value in (
        ("seller-agent-url", seller_agent_url),
        ("buyer-agent-url", buyer_agent_url),
    ):
        if value:
            _validate_url(value=value, label=label, errors=errors)
    identity_registry = agent_env["IDENTITY_REGISTRY_ADDRESS"]
    for label, value in (
        ("seller-agent-id", seller_agent_id),
        ("buyer-agent-id", buyer_agent_id),
    ):
        if value:
            _validate_agent_id(value, label, expected_chain_id, identity_registry, errors)
    for label, value in (
        ("seller-private-key", seller_private_key),
        ("buyer-private-key", buyer_private_key),
    ):
        if value:
            _validate_private_key(value, label, errors)
    if ssh_private_key_path:
        ssh_path = Path(ssh_private_key_path).expanduser()
        if not ssh_path.exists():
            errors.append(f"ssh-private-key-path does not exist: {ssh_private_key_path}")
        elif ssh_path.is_dir():
            errors.append(f"ssh-private-key-path must point to a file: {ssh_private_key_path}")

    return errors


def validate_bundle(
    *,
    agent_env_path: Path,
    provisioning_env_path: Path,
    registry_env_path: Path,
    inventory_path: Path = DEFAULT_INVENTORY_PATH,
    expected_chain_name: str = "base-sepolia",
    expected_chain_id: int = 84532,
    seller_agent_url: str | None = None,
    buyer_agent_url: str | None = None,
    seller_agent_id: str | None = None,
    buyer_agent_id: str | None = None,
    seller_private_key: str | None = None,
    buyer_private_key: str | None = None,
    ssh_private_key_path: str | None = None,
) -> list[str]:
    for path in (agent_env_path, provisioning_env_path, registry_env_path, inventory_path):
        if not path.exists():
            return [f"Missing required file: {path}"]

    agent_env = _parse_env_file(agent_env_path)
    provisioning_env = _parse_env_file(provisioning_env_path)
    registry_env = _parse_env_file(registry_env_path)
    inventory_hosts = _parse_inventory_hosts(inventory_path)
    return _validate_bundle(
        agent_env=agent_env,
        provisioning_env=provisioning_env,
        registry_env=registry_env,
        inventory_hosts=inventory_hosts,
        expected_chain_name=expected_chain_name,
        expected_chain_id=expected_chain_id,
        seller_agent_url=seller_agent_url,
        buyer_agent_url=buyer_agent_url,
        seller_agent_id=seller_agent_id,
        buyer_agent_id=buyer_agent_id,
        seller_private_key=seller_private_key,
        buyer_private_key=buyer_private_key,
        ssh_private_key_path=ssh_private_key_path,
    )


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", help="Label for the env bundle under test")
    parser.add_argument("--agent-env", required=True, type=Path)
    parser.add_argument("--provisioning-env", required=True, type=Path)
    parser.add_argument("--registry-env", required=True, type=Path)
    parser.add_argument("--inventory-path", type=Path, default=DEFAULT_INVENTORY_PATH)
    parser.add_argument("--expected-chain-name", default="base-sepolia")
    parser.add_argument("--expected-chain-id", type=int, default=84532)
    parser.add_argument("--seller-agent-url")
    parser.add_argument("--buyer-agent-url")
    parser.add_argument("--seller-agent-id")
    parser.add_argument("--buyer-agent-id")
    parser.add_argument("--seller-private-key")
    parser.add_argument("--buyer-private-key")
    parser.add_argument("--ssh-private-key-path")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    errors = validate_bundle(
        agent_env_path=args.agent_env,
        provisioning_env_path=args.provisioning_env,
        registry_env_path=args.registry_env,
        inventory_path=args.inventory_path,
        expected_chain_name=args.expected_chain_name,
        expected_chain_id=args.expected_chain_id,
        seller_agent_url=args.seller_agent_url,
        buyer_agent_url=args.buyer_agent_url,
        seller_agent_id=args.seller_agent_id,
        buyer_agent_id=args.buyer_agent_id,
        seller_private_key=args.seller_private_key,
        buyer_private_key=args.buyer_private_key,
        ssh_private_key_path=args.ssh_private_key_path,
    )
    if errors:
        label = f" for {args.environment}" if args.environment else ""
        print(f"Deployment bundle validation failed{label}:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    label = f" for {args.environment}" if args.environment else ""
    print(f"Deployment bundle validation passed{label}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
