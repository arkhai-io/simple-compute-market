#!/usr/bin/env python3
"""Validate a production-style deployment env bundle before a canary run."""

from __future__ import annotations

import argparse
import ipaddress
import re
import sys
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY_PATH = ROOT / "compute-provisioning-iac/ansible/inventory/hosts"
AGENT_DATA_DIR = ROOT / "core/agent/app/data"
LOCAL_ONLY_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "host.docker.internal"}
PUBLIC_RPC_HOSTS = {"sepolia.base.org"}
PLACEHOLDER_RE = re.compile(r"<[^>]+>")
EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
PRIVATE_KEY_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
AGENT_ID_RE = re.compile(r"^eip155:(?P<chain_id>\d+):(?P<registry>0x[0-9a-fA-F]{40}):(?P<token_id>\d+)$")
SPACE_SENSITIVE_AGENT_KEYS = {"AGENT_NAME", "SSH_PUBLIC_KEY"}

AGENT_REQUIRED_KEYS = {
    "GEMINI_API_KEY",
    "BASE_URL_OVERRIDE",
    "PORT",
    "AGENT_ID",
    "AUTO_REGISTER",
    "ENABLE_EVENT_QUEUE",
    "IDENTITY_REGISTRY_ADDRESS",
    "REPUTATION_REGISTRY_ADDRESS",
    "VALIDATION_REGISTRY_ADDRESS",
    "CHAIN_ID",
    "REGISTRY_URL",
    "CHAIN_RPC_URL",
    "AGENT_PRIV_KEY",
    "AGENT_WALLET_ADDRESS",
    "CHAIN_NAME",
    "TOKEN_REGISTRY_PATH",
    "SSH_PUBLIC_KEY",
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


def _validate_quoted_space_sensitive_values(
    path: Path,
    *,
    label: str,
    keys: set[str],
    errors: list[str],
) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        if key not in keys:
            continue
        raw_value = raw_value.strip()
        if " " not in raw_value:
            continue
        if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in {"'", '"'}:
            continue
        errors.append(f"{label}:{key} must quote values containing spaces")


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


def _validate_rpc_url(value: str, label: str, errors: list[str]) -> None:
    _validate_url(
        value=value,
        label=label,
        errors=errors,
        allow_local_host=True,
    )
    normalized = _normalize_env_value(value)
    if _is_placeholder(normalized):
        return
    hostname = urlparse(normalized).hostname
    if hostname in PUBLIC_RPC_HOSTS:
        errors.append(
            f"{label}: public Base Sepolia RPC endpoint is not allowed for deployed canaries; "
            "use an authenticated provider or private RPC"
        )


def _validate_agent_rpc_url(value: str, label: str, errors: list[str]) -> None:
    normalized = _normalize_env_value(value)
    if _is_placeholder(normalized):
        errors.append(f"{label}: placeholder value is not allowed: {value}")
        return

    parsed = urlparse(normalized)
    if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
        errors.append(f"{label}: expected a WebSocket RPC URL (ws:// or wss://), got: {value}")
        return
    if parsed.hostname in LOCAL_ONLY_HOSTS:
        errors.append(f"{label}: local-only host is not allowed: {value}")
        return
    if parsed.hostname in PUBLIC_RPC_HOSTS:
        errors.append(
            f"{label}: public Base Sepolia RPC endpoint is not allowed for deployed canaries; "
            "use an authenticated provider or private RPC"
        )


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


def _validate_ip_address(value: str, label: str, errors: list[str]) -> None:
    normalized = _normalize_env_value(value)
    if _is_placeholder(normalized):
        errors.append(f"{label}: placeholder value is not allowed: {value}")
        return
    try:
        ipaddress.ip_address(normalized)
    except ValueError:
        errors.append(f"{label}: invalid IP address: {value}")


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


def _validate_token_registry_path(value: str, label: str, errors: list[str]) -> None:
    normalized = _normalize_env_value(value)
    if _is_placeholder(normalized):
        errors.append(f"{label}: placeholder value is not allowed: {value}")
        return

    candidate = AGENT_DATA_DIR / Path(normalized).name
    if not candidate.exists():
        errors.append(
            f"{label}: token registry file is not present in core/agent/app/data: {Path(normalized).name}"
        )


def _compare_equal(left: str, left_label: str, right: str, right_label: str, errors: list[str]) -> None:
    if _normalize_env_value(left) != _normalize_env_value(right):
        errors.append(
            f"{left_label} must match {right_label}: {left_label}={left!r}, {right_label}={right!r}"
        )


def _validate_agent_env(
    *,
    agent_env: dict[str, str],
    label: str,
    provisioning_env: dict[str, str],
    registry_env: dict[str, str],
    inventory_hosts: set[str],
    expected_chain_name: str,
    expected_chain_id: int,
    seller_agent_url: str | None,
    buyer_agent_url: str | None,
    seller_agent_id: str | None,
    buyer_agent_id: str | None,
    expected_registered_agent_id: str | None,
    seller_private_key: str | None,
    buyer_private_key: str | None,
    ssh_private_key_path: str | None,
) -> list[str]:
    errors: list[str] = []

    _validate_required_keys(agent_env, AGENT_REQUIRED_KEYS, label, errors)
    if errors:
        return errors

    inventory_hosts = set(inventory_hosts)

    _validate_non_empty_secret(agent_env["GEMINI_API_KEY"], f"{label}:GEMINI_API_KEY", errors)
    _validate_url(
        value=agent_env["BASE_URL_OVERRIDE"],
        label=f"{label}:BASE_URL_OVERRIDE",
        errors=errors,
        allow_zerotier_ip=True,
    )
    _validate_url(
        value=agent_env["REGISTRY_URL"],
        label=f"{label}:REGISTRY_URL",
        errors=errors,
    )
    _validate_url(
        value=agent_env["PROVISIONING_SERVICE_URL"],
        label=f"{label}:PROVISIONING_SERVICE_URL",
        errors=errors,
    )
    _validate_agent_rpc_url(
        agent_env["CHAIN_RPC_URL"],
        f"{label}:CHAIN_RPC_URL",
        errors,
    )
    _validate_private_key(agent_env["AGENT_PRIV_KEY"], f"{label}:AGENT_PRIV_KEY", errors)
    _validate_evm_address(
        agent_env["AGENT_WALLET_ADDRESS"], f"{label}:AGENT_WALLET_ADDRESS", errors
    )
    _validate_token_registry_path(
        agent_env["TOKEN_REGISTRY_PATH"], f"{label}:TOKEN_REGISTRY_PATH", errors
    )
    _validate_ssh_public_key(agent_env["SSH_PUBLIC_KEY"], f"{label}:SSH_PUBLIC_KEY", errors)
    if _normalize_env_value(agent_env["CHAIN_NAME"]) != expected_chain_name:
        errors.append(
            f"{label}:CHAIN_NAME must be {expected_chain_name}, got {agent_env['CHAIN_NAME']}"
        )
    if _normalize_env_value(agent_env["PROVISIONING_MODE"]) != "http":
        errors.append(
            f"{label}:PROVISIONING_MODE must be http, got {agent_env['PROVISIONING_MODE']}"
        )
    if _normalize_env_value(agent_env["AUTO_REGISTER"]).lower() != "true":
        errors.append(f"{label}:AUTO_REGISTER must be true for deployed canaries")
    if _normalize_env_value(agent_env["ENABLE_EVENT_QUEUE"]).lower() != "false":
        errors.append(f"{label}:ENABLE_EVENT_QUEUE must be false for deployed canaries")

    for key in (
        "IDENTITY_REGISTRY_ADDRESS",
        "REPUTATION_REGISTRY_ADDRESS",
        "VALIDATION_REGISTRY_ADDRESS",
    ):
        _validate_evm_address(agent_env[key], f"{label}:{key}", errors)
        _validate_evm_address(registry_env[key], f"registry env:{key}", errors)
        _compare_equal(agent_env[key], f"{label}:{key}", registry_env[key], f"registry env:{key}", errors)

    persisted_onchain_agent_id = _normalize_env_value(agent_env.get("ONCHAIN_AGENT_ID", ""))
    if persisted_onchain_agent_id:
        _validate_agent_id(
            persisted_onchain_agent_id,
            f"{label}:ONCHAIN_AGENT_ID",
            expected_chain_id,
            agent_env["IDENTITY_REGISTRY_ADDRESS"],
            errors,
        )
        if expected_registered_agent_id:
            _compare_equal(
                agent_env["ONCHAIN_AGENT_ID"],
                f"{label}:ONCHAIN_AGENT_ID",
                expected_registered_agent_id,
                "expected canary agent id",
                errors,
            )

    default_vm_host = _normalize_env_value(agent_env["DEFAULT_VM_HOST"])
    if default_vm_host not in inventory_hosts:
        errors.append(f"{label}:DEFAULT_VM_HOST is not in inventory: {default_vm_host}")
    base_url = _normalize_env_value(agent_env["BASE_URL_OVERRIDE"])
    zerotier_network = _normalize_env_value(agent_env.get("ZEROTIER_NETWORK", ""))
    zerotier_ip = _normalize_env_value(agent_env.get("ZEROTIER_IP", ""))

    if zerotier_network:
        _validate_zerotier_network(
            agent_env["ZEROTIER_NETWORK"], f"{label}:ZEROTIER_NETWORK", errors
        )
        _compare_equal(
            agent_env["ZEROTIER_NETWORK"],
            f"{label}:ZEROTIER_NETWORK",
            provisioning_env["ZEROTIER_NETWORK"],
            "provisioning env:ZEROTIER_NETWORK",
            errors,
        )
        _compare_equal(
            agent_env["ZEROTIER_NETWORK"],
            f"{label}:ZEROTIER_NETWORK",
            registry_env["ZEROTIER_NETWORK"],
            "registry env:ZEROTIER_NETWORK",
            errors,
        )
        if zerotier_ip:
            _validate_ip_address(zerotier_ip, f"{label}:ZEROTIER_IP", errors)
    else:
        if "{ZEROTIER_IP}" in base_url:
            errors.append(
                f"{label}:ZEROTIER_NETWORK is required when BASE_URL_OVERRIDE uses {{ZEROTIER_IP}}"
            )
        if not zerotier_ip:
            errors.append(
                f"{label}: provide ZEROTIER_NETWORK or ZEROTIER_IP for deployed canaries"
            )
        else:
            _validate_ip_address(zerotier_ip, f"{label}:ZEROTIER_IP", errors)
            parsed_base_url = urlparse(base_url)
            if parsed_base_url.hostname and parsed_base_url.hostname != zerotier_ip:
                errors.append(
                    f"{label}:BASE_URL_OVERRIDE hostname must match {label}:ZEROTIER_IP: "
                    f"{parsed_base_url.hostname!r} != {zerotier_ip!r}"
                )
    _compare_equal(
        agent_env["REGISTRY_URL"],
        f"{label}:REGISTRY_URL",
        provisioning_env["REGISTRY_URL"],
        "provisioning env:REGISTRY_URL",
        errors,
    )

    return errors


def _validate_shared_infra_envs(
    *,
    provisioning_env: dict[str, str],
    registry_env: dict[str, str],
    inventory_hosts: set[str],
    expected_chain_id: int,
) -> list[str]:
    errors: list[str] = []

    _validate_required_keys(
        provisioning_env, PROVISIONING_REQUIRED_KEYS, "provisioning env", errors
    )
    _validate_required_keys(registry_env, REGISTRY_REQUIRED_KEYS, "registry env", errors)

    if errors:
        return errors

    inventory_hosts = set(inventory_hosts)

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
    _validate_rpc_url(
        registry_env["RPC_URL"],
        "registry env:RPC_URL",
        errors,
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

    if _normalize_env_value(provisioning_env["DEFAULT_VM_HOST"]) not in inventory_hosts:
        errors.append(
            "provisioning env:DEFAULT_VM_HOST is not in inventory: "
            f"{provisioning_env['DEFAULT_VM_HOST']}"
        )

    return errors


def _validate_actor_relationships(
    *,
    seller_agent_env: dict[str, str],
    buyer_agent_env: dict[str, str],
    provisioning_env: dict[str, str],
    errors: list[str],
) -> None:
    distinct_keys = (
        "AGENT_ID",
        "AGENT_PRIV_KEY",
        "AGENT_WALLET_ADDRESS",
        "BASE_URL_OVERRIDE",
    )
    for key in distinct_keys:
        seller_value = _normalize_env_value(seller_agent_env[key])
        buyer_value = _normalize_env_value(buyer_agent_env[key])
        if key == "BASE_URL_OVERRIDE" and seller_value == buyer_value and "{ZEROTIER_IP}" in seller_value:
            continue
        if seller_value == buyer_value:
            errors.append(f"seller agent env and buyer agent env must not share {key}")

    if "ZEROTIER_IP" in seller_agent_env and "ZEROTIER_IP" in buyer_agent_env:
        seller_zerotier_ip = _normalize_env_value(seller_agent_env["ZEROTIER_IP"])
        buyer_zerotier_ip = _normalize_env_value(buyer_agent_env["ZEROTIER_IP"])
        if seller_zerotier_ip == buyer_zerotier_ip:
            errors.append("seller agent env and buyer agent env must not share ZEROTIER_IP")

    shared_keys = (
        "CHAIN_NAME",
        "CHAIN_RPC_URL",
        "IDENTITY_REGISTRY_ADDRESS",
        "REPUTATION_REGISTRY_ADDRESS",
        "VALIDATION_REGISTRY_ADDRESS",
        "REGISTRY_URL",
        "PROVISIONING_MODE",
        "PROVISIONING_SERVICE_URL",
    )
    for key in shared_keys:
        _compare_equal(
            seller_agent_env[key],
            f"seller agent env:{key}",
            buyer_agent_env[key],
            f"buyer agent env:{key}",
            errors,
        )

    if "ZEROTIER_NETWORK" in seller_agent_env and "ZEROTIER_NETWORK" in buyer_agent_env:
        _compare_equal(
            seller_agent_env["ZEROTIER_NETWORK"],
            "seller agent env:ZEROTIER_NETWORK",
            buyer_agent_env["ZEROTIER_NETWORK"],
            "buyer agent env:ZEROTIER_NETWORK",
            errors,
        )
    _compare_equal(
        seller_agent_env["DEFAULT_VM_HOST"],
        "seller agent env:DEFAULT_VM_HOST",
        provisioning_env["DEFAULT_VM_HOST"],
        "provisioning env:DEFAULT_VM_HOST",
        errors,
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
    errors = _validate_shared_infra_envs(
        provisioning_env=provisioning_env,
        registry_env=registry_env,
        inventory_hosts=inventory_hosts,
        expected_chain_id=expected_chain_id,
    )
    errors.extend(
        _validate_agent_env(
            agent_env=agent_env,
            label="agent env",
            provisioning_env=provisioning_env,
            registry_env=registry_env,
            inventory_hosts=inventory_hosts,
            expected_chain_name=expected_chain_name,
            expected_chain_id=expected_chain_id,
            seller_agent_url=seller_agent_url,
            buyer_agent_url=buyer_agent_url,
            seller_agent_id=seller_agent_id,
            buyer_agent_id=buyer_agent_id,
            expected_registered_agent_id=seller_agent_id or buyer_agent_id,
            seller_private_key=seller_private_key,
            buyer_private_key=buyer_private_key,
            ssh_private_key_path=ssh_private_key_path,
        )
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
    expected_chain_name: str = "base_sepolia",
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
    errors = _validate_bundle(
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
    _validate_quoted_space_sensitive_values(
        agent_env_path,
        label="agent env",
        keys=SPACE_SENSITIVE_AGENT_KEYS,
        errors=errors,
    )
    return errors


def validate_actor_bundle(
    *,
    seller_agent_env_path: Path,
    buyer_agent_env_path: Path,
    provisioning_env_path: Path,
    registry_env_path: Path,
    inventory_path: Path = DEFAULT_INVENTORY_PATH,
    expected_chain_name: str = "base_sepolia",
    expected_chain_id: int = 84532,
    seller_agent_url: str | None = None,
    buyer_agent_url: str | None = None,
    seller_agent_id: str | None = None,
    buyer_agent_id: str | None = None,
    seller_private_key: str | None = None,
    buyer_private_key: str | None = None,
    ssh_private_key_path: str | None = None,
) -> list[str]:
    for path in (
        seller_agent_env_path,
        buyer_agent_env_path,
        provisioning_env_path,
        registry_env_path,
        inventory_path,
    ):
        if not path.exists():
            return [f"Missing required file: {path}"]

    seller_agent_env = _parse_env_file(seller_agent_env_path)
    buyer_agent_env = _parse_env_file(buyer_agent_env_path)
    provisioning_env = _parse_env_file(provisioning_env_path)
    registry_env = _parse_env_file(registry_env_path)
    inventory_hosts = _parse_inventory_hosts(inventory_path)

    errors = _validate_shared_infra_envs(
        provisioning_env=provisioning_env,
        registry_env=registry_env,
        inventory_hosts=inventory_hosts,
        expected_chain_id=expected_chain_id,
    )
    errors.extend(
        _validate_agent_env(
            agent_env=seller_agent_env,
            label="seller agent env",
            provisioning_env=provisioning_env,
            registry_env=registry_env,
            inventory_hosts=inventory_hosts,
            expected_chain_name=expected_chain_name,
            expected_chain_id=expected_chain_id,
            seller_agent_url=seller_agent_url,
            buyer_agent_url=buyer_agent_url,
            seller_agent_id=seller_agent_id,
            buyer_agent_id=buyer_agent_id,
            expected_registered_agent_id=seller_agent_id,
            seller_private_key=seller_private_key,
            buyer_private_key=buyer_private_key,
            ssh_private_key_path=ssh_private_key_path,
        )
    )
    errors.extend(
        _validate_agent_env(
            agent_env=buyer_agent_env,
            label="buyer agent env",
            provisioning_env=provisioning_env,
            registry_env=registry_env,
            inventory_hosts=inventory_hosts,
            expected_chain_name=expected_chain_name,
            expected_chain_id=expected_chain_id,
            seller_agent_url=seller_agent_url,
            buyer_agent_url=buyer_agent_url,
            seller_agent_id=seller_agent_id,
            buyer_agent_id=buyer_agent_id,
            expected_registered_agent_id=buyer_agent_id,
            seller_private_key=seller_private_key,
            buyer_private_key=buyer_private_key,
            ssh_private_key_path=ssh_private_key_path,
        )
    )
    _validate_actor_relationships(
        seller_agent_env=seller_agent_env,
        buyer_agent_env=buyer_agent_env,
        provisioning_env=provisioning_env,
        errors=errors,
    )
    _validate_quoted_space_sensitive_values(
        seller_agent_env_path,
        label="seller agent env",
        keys=SPACE_SENSITIVE_AGENT_KEYS,
        errors=errors,
    )
    _validate_quoted_space_sensitive_values(
        buyer_agent_env_path,
        label="buyer agent env",
        keys=SPACE_SENSITIVE_AGENT_KEYS,
        errors=errors,
    )

    for label, value, registry in (
        ("seller-agent-id", seller_agent_id, seller_agent_env["IDENTITY_REGISTRY_ADDRESS"]),
        ("buyer-agent-id", buyer_agent_id, buyer_agent_env["IDENTITY_REGISTRY_ADDRESS"]),
    ):
        if value:
            _validate_agent_id(value, label, expected_chain_id, registry, errors)

    return errors


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", help="Label for the env bundle under test")
    parser.add_argument("--agent-env", type=Path)
    parser.add_argument("--seller-agent-env", type=Path)
    parser.add_argument("--buyer-agent-env", type=Path)
    parser.add_argument("--provisioning-env", required=True, type=Path)
    parser.add_argument("--registry-env", required=True, type=Path)
    parser.add_argument("--inventory-path", type=Path, default=DEFAULT_INVENTORY_PATH)
    parser.add_argument("--expected-chain-name", default="base_sepolia")
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
    if args.agent_env and (args.seller_agent_env or args.buyer_agent_env):
        print(
            "Specify either --agent-env or both --seller-agent-env and --buyer-agent-env, not both.",
            file=sys.stderr,
        )
        return 2
    if args.seller_agent_env or args.buyer_agent_env:
        if not (args.seller_agent_env and args.buyer_agent_env):
            print(
                "Provide both --seller-agent-env and --buyer-agent-env when validating a dual-agent bundle.",
                file=sys.stderr,
            )
            return 2
        errors = validate_actor_bundle(
            seller_agent_env_path=args.seller_agent_env,
            buyer_agent_env_path=args.buyer_agent_env,
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
    else:
        if not args.agent_env:
            print(
                "Provide either --agent-env or both --seller-agent-env and --buyer-agent-env.",
                file=sys.stderr,
            )
            return 2
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
