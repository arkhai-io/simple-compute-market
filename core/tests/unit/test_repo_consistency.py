from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from service.clients.alkahest import BASE_SEPOLIA_ADDRESSES


ROOT = Path(__file__).resolve().parents[3]
ASYNC_PROD_ENV = ROOT / "async-provisioning-service/.env.production.sample"
AGENT_PROD_ENV = ROOT / "core/agent/.env.production.sample"
INVENTORY_PATH = ROOT / "compute-provisioning-iac/ansible/inventory/hosts"
ASYNC_DOCKERFILE = ROOT / "async-provisioning-service/Dockerfile"
ASYNC_README = ROOT / "async-provisioning-service/README.md"
RUNBOOK_PATH = ROOT / "docs/production-canary.md"
CANARY_MODULE_PATH = ROOT / "cli/market/canary.py"
ALKAHEST_REPO = ROOT.parent / "alkahest"
ALKAHEST_BASE_DEPLOYMENT = (
    ALKAHEST_REPO / "contracts/deployments/deployment_base_sepolia.json"
)


def _parse_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env[key] = value
    return env


def _parse_inventory(path: Path) -> dict[str, set[str]]:
    inventory: dict[str, set[str]] = {}
    section: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
            inventory.setdefault(section, set())
            continue
        if section is None:
            continue
        alias = stripped.split()[0]
        inventory[section].add(alias)
    return inventory


def _parse_script_args(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r'add_argument\("(?P<arg>--[a-z0-9-]+)"', text))


def _parse_runbook_args(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    section_match = re.search(
        r"## Canary smoke run\s+(?P<section>.*?)(?:\n## |\Z)",
        text,
        re.DOTALL,
    )
    if section_match:
        text = section_match.group("section")
    ignored = {"--no-config"}
    return {
        arg
        for arg in re.findall(r"(--[a-z0-9-]+)", text)
        if arg not in ignored
    }


def test_async_provisioning_production_sample_includes_required_runtime_vars() -> None:
    env = _parse_env_file(ASYNC_PROD_ENV)
    required = {
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

    missing = sorted(required - env.keys())
    assert not missing, f"Missing required async provisioning env vars: {missing}"
    assert env["ENABLE_AUTH"] == "true"
    assert env["AUTH_FAIL_OPEN"] == "false"


def test_async_provisioning_contract_does_not_reference_admin_secret() -> None:
    dockerfile_text = ASYNC_DOCKERFILE.read_text(encoding="utf-8")
    readme_text = ASYNC_README.read_text(encoding="utf-8")
    sample_text = ASYNC_PROD_ENV.read_text(encoding="utf-8")

    assert "ADMIN_SECRET" not in dockerfile_text
    assert "ADMIN_SECRET" not in readme_text
    assert "ADMIN_SECRET" not in sample_text


def test_production_default_vm_hosts_exist_in_inventory() -> None:
    inventory = _parse_inventory(INVENTORY_PATH)
    kvm_hosts = inventory.get("kvm_hosts", set())
    agent_env = _parse_env_file(AGENT_PROD_ENV)
    provisioning_env = _parse_env_file(ASYNC_PROD_ENV)

    defaults = {
        "core/agent/.env.production.sample": agent_env["DEFAULT_VM_HOST"],
        "async-provisioning-service/.env.production.sample": provisioning_env[
            "DEFAULT_VM_HOST"
        ],
    }
    missing = [
        f"{source} -> {vm_host}"
        for source, vm_host in defaults.items()
        if vm_host not in kvm_hosts
    ]
    assert not missing, f"Unknown DEFAULT_VM_HOST values: {missing}"


def test_inventory_contains_environment_host_aliases() -> None:
    inventory = _parse_inventory(INVENTORY_PATH)
    required = {
        "frp_servers": {"proxy-dev", "proxy-staging", "proxy-production"},
        "provisioning_servers": {
            "provisioning-dev",
            "provisioning-staging",
            "provisioning-production",
        },
        "kvm_hosts": {"ww1"},
    }

    missing: list[str] = []
    for section, aliases in required.items():
        section_aliases = inventory.get(section, set())
        for alias in sorted(aliases - section_aliases):
            missing.append(f"{section}:{alias}")
    assert not missing, f"Missing inventory aliases: {missing}"


def test_production_canary_runbook_matches_smoke_script_cli() -> None:
    script_args = _parse_script_args(CANARY_MODULE_PATH)
    runbook_args = _parse_runbook_args(RUNBOOK_PATH)
    documented_required_args = {
        "--registry-url",
        "--provisioning-url",
        "--seller-agent-url",
        "--buyer-agent-url",
        "--seller-agent-id",
        "--buyer-agent-id",
        "--seller-private-key",
        "--buyer-private-key",
        "--gpu-model",
        "--region",
        "--token-symbol",
        "--token-amount",
        "--ssh-private-key-path",
    }

    undocumented = sorted(documented_required_args - runbook_args)
    unknown = sorted(runbook_args - script_args)
    assert not undocumented, f"Runbook is missing documented required args: {undocumented}"
    assert not unknown, f"Runbook references args not supported by smoke script: {unknown}"


def test_base_sepolia_service_addresses_match_alkahest_deployment_when_available() -> None:
    if not ALKAHEST_BASE_DEPLOYMENT.exists():
        pytest.skip("Sibling alkahest repo is not present next to simple-market-service")

    deployment = json.loads(ALKAHEST_BASE_DEPLOYMENT.read_text(encoding="utf-8"))
    required_mapping = {
        ("arbiters_addresses", "trivial_arbiter"): "trivialArbiter",
        ("arbiters_addresses", "trusted_oracle_arbiter"): "trustedOracleArbiter",
        ("string_obligation_addresses", "obligation"): "stringObligation",
        ("erc20_addresses", "barter_utils"): "erc20BarterUtils",
        ("erc20_addresses", "escrow_obligation_nontierable"): "erc20EscrowObligation",
        ("erc20_addresses", "payment_obligation"): "erc20PaymentObligation",
        ("erc721_addresses", "barter_utils"): "erc721BarterUtils",
        ("erc721_addresses", "escrow_obligation_nontierable"): "erc721EscrowObligation",
        ("erc721_addresses", "payment_obligation"): "erc721PaymentObligation",
        ("erc1155_addresses", "barter_utils"): "erc1155BarterUtils",
        ("erc1155_addresses", "escrow_obligation_nontierable"): "erc1155EscrowObligation",
        ("erc1155_addresses", "payment_obligation"): "erc1155PaymentObligation",
        ("token_bundle_addresses", "barter_utils"): "tokenBundleBarterUtils",
        ("token_bundle_addresses", "escrow_obligation_nontierable"): "tokenBundleEscrowObligation",
        ("token_bundle_addresses", "payment_obligation"): "tokenBundlePaymentObligation",
        ("attestation_addresses", "barter_utils"): "attestationBarterUtils",
        ("attestation_addresses", "escrow_obligation_nontierable"): "attestationEscrowObligation",
        ("attestation_addresses", "escrow_obligation_2_nontierable"): "attestationEscrowObligation2",
    }

    mismatches: list[str] = []
    for (section, key), deployment_key in required_mapping.items():
        actual = BASE_SEPOLIA_ADDRESSES[section][key].lower()
        expected = str(deployment[deployment_key]).lower()
        if actual != expected:
            mismatches.append(
                f"{section}.{key}: service={BASE_SEPOLIA_ADDRESSES[section][key]} "
                f"alkahest={deployment[deployment_key]}"
            )

    assert not mismatches, "Base Sepolia Alkahest address drift detected:\n" + "\n".join(
        mismatches
    )
