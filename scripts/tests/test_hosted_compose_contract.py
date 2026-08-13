from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
import tomllib

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = (REPO_ROOT / "compose.hosted-settlement.yml").read_text(encoding="utf-8")
ROOT_MAKE = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
E2E_MAKE = (REPO_ROOT / "e2e-tests" / "Makefile").read_text(encoding="utf-8")


def test_authority_port_coexists_with_registry_container_port() -> None:
    base = (REPO_ROOT / "domains" / "vms" / "compose.yml").read_text(encoding="utf-8")
    assert '"8080:8080"' in base
    assert '"127.0.0.1:${HOSTED_SETTLEMENT_HOST_PORT:-18080}:8080"' in COMPOSE
    assert "http://hosted-settlement-api:8080" in COMPOSE
    assert "network_mode: service:hosted-settlement-api" in COMPOSE
    assert "aliases: [bob-storefront]" in COMPOSE


def test_control_and_provider_services_are_internal_only() -> None:
    assert "hosted-control:\n    internal: true" in COMPOSE
    assert "hosted-provider:\n    internal: true" in COMPOSE
    control = COMPOSE.split("  hosted-settlement-control:", 1)[1].split(
        "  hosted-settlement-admit-fixture:", 1
    )[0]
    assert "networks: [hosted-control]" in control
    assert "ports:" not in control
    admission = COMPOSE.split("  hosted-settlement-admit-fixture:", 1)[1].split(
        "  hosted-settlement-api:", 1
    )[0]
    assert "networks: [hosted-provider, hosted-control]" in admission
    assert "ports:" not in admission
    api = COMPOSE.split("  hosted-settlement-api:", 1)[1].split(
        "  hosted-settlement-worker:", 1
    )[0]
    assert "hosted-provider: {}" in api
    worker = COMPOSE.split("  hosted-settlement-worker:", 1)[1].split(
        "  hosted-settlement-event-worker:", 1
    )[0]
    assert "networks: [default, hosted-provider]" in worker


def test_compose_has_no_source_or_editable_sibling_mount() -> None:
    lowered = COMPOSE.lower()
    assert "../hosted-settlement" not in lowered
    assert "editable" not in lowered
    assert "/src" not in lowered
    assert "source: ${HOSTED_SETTLEMENT_RELEASE_DIR" in COMPOSE
    assert "read_only: true" in COMPOSE


def test_hosted_storefront_uses_hosted_inventory_seed() -> None:
    storefront = COMPOSE.split("  bob-storefront:", 1)[1].split("\nvolumes:", 1)[0]
    assert (
        "e2e-tests/config/hosted-resources.csv:/app/hosted-resources.csv:ro"
        in storefront
    )
    provisioning = COMPOSE.split("  provisioning:", 1)[1].split("  bob-storefront:", 1)[
        0
    ]
    assert "PROVISIONING_INVENTORY_INI:" in provisioning
    assert "kvm1 ansible_host=127.0.0.1 ansible_user=stub" in provisioning


def test_secret_environment_files_are_required_and_not_generated() -> None:
    assert "HOSTED_SETTLEMENT_ENV_FILE:?" in COMPOSE
    assert "HOSTED_SETTLEMENT_E2E_ENV_FILE:?" in COMPOSE
    assert "HOSTED_SETTLEMENT_E2E_RUNNER_ENV_FILE:?" in COMPOSE
    assert COMPOSE.count("required: true") >= 3
    preparer = (REPO_ROOT / "scripts" / "prepare-hosted-compose.py").read_text(
        encoding="utf-8"
    )
    for token in ("SECRET", "TOKEN", "CREDENTIAL", "PRIVATE_KEY", "WEBHOOK"):
        assert token in preparer


def test_clean_and_restart_targets_have_opposite_volume_behavior() -> None:
    restart = ROOT_MAKE.split("hosted-compose-restart:", 1)[1].split(
        "hosted-compose-clean:", 1
    )[0]
    clean = ROOT_MAKE.split("hosted-compose-clean:", 1)[1].split("hosted-hermetic:", 1)[
        0
    ]
    assert " restart" in restart
    assert " down -v --remove-orphans" in clean
    assert "down -v" not in restart
    for variable in (
        "VMS_REGISTRY_ADMIN_API_KEY",
        "VMS_REGISTRY_BOOTSTRAP_API_KEY",
        "VMS_BOB_STOREFRONT_SECRETS_FILE",
        "VMS_REGISTRY_IDENTITY_CREDENTIAL_FILE",
        "VMS_REGISTRY_B_IDENTITY_CREDENTIAL_FILE",
        "VMS_PROVISIONING_IDENTITY_ENV_FILE",
    ):
        assert variable in clean


def test_explicit_lanes_and_hosted_only_image_target_exist() -> None:
    for target in (
        "hosted-preflight:",
        "hosted-hermetic-preflight:",
        "hosted-compose-start:",
        "hosted-compose-restart:",
        "hosted-compose-clean:",
        "hosted-hermetic:",
        "hosted-local-eas:",
        "hosted-real-stripe:",
    ):
        assert target in ROOT_MAKE
    assert "build-hosted:" in E2E_MAKE
    assert "--target hosted" in E2E_MAKE


def test_wallet_free_fixtures_have_only_public_portable_configuration() -> None:
    forbidden = {
        "wallet",
        "chains",
        "rpc_url",
        "private_key",
        "webhook",
        "database",
        "administrator",
        "control_url",
        "stripe_secret",
        "provider",
    }

    def field_paths(value: object) -> set[str]:
        if not isinstance(value, Mapping):
            return set()
        result = {str(key).lower() for key in value}
        for child in value.values():
            result.update(field_paths(child))
        return result

    expected_urls = {
        "hosted-storefront.toml": "http://127.0.0.1:8080",
        "hosted-buyer.toml": "http://hosted-settlement-api:8080",
    }
    for filename, expected_url in expected_urls.items():
        path = REPO_ROOT / "e2e-tests" / "config" / filename
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        assert "Identity" in document
        assert document["Settlement"]["stripe"]["enabled"] is True
        assert document["Settlement"]["stripe"]["base_url"] == expected_url
        assert field_paths(document).isdisjoint(forbidden)


@pytest.mark.parametrize(
    "field,value",
    (
        ("manifest_digest", "sha256:" + "0" * 64),
        ("schema_version", 3),
        ("capabilities", []),
    ),
)
def test_ready_gate_rejects_digest_schema_and_capability_mismatch(
    field: str, value: object
) -> None:
    import importlib.util

    path = REPO_ROOT / "scripts" / "verify-hosted-release.py"
    spec = importlib.util.spec_from_file_location("hosted_ready_verifier", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    production = {
        "manifest_digest": "sha256:" + "1" * 64,
        "api_version": "0.1.0",
        "schema_version": 4,
        "capabilities": ["required.v1"],
    }
    response = {
        "ready": True,
        "manifest_digest": production["manifest_digest"],
        "api_version": production["api_version"],
        "schema_version": production["schema_version"],
        "capabilities": production["capabilities"],
    }
    response[field] = value
    with pytest.raises(module.ReleaseVerificationError, match="ready response"):
        module.verify_ready_response(production, response)


def test_hermetic_ready_gate_rejects_wrong_control_version() -> None:
    import importlib.util

    path = REPO_ROOT / "scripts" / "verify-hosted-release.py"
    spec = importlib.util.spec_from_file_location("hosted_control_verifier", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    production = {
        "manifest_digest": "sha256:" + "1" * 64,
        "api_version": "0.1.0",
        "schema_version": 4,
        "capabilities": [],
    }
    e2e = {
        "manifest_digest": "sha256:" + "2" * 64,
        "control_protocol": "arkhai.hosted-settlement-e2e-control.v1",
        "capabilities": [],
    }
    response = {
        "ready": True,
        "manifest_digest": production["manifest_digest"],
        "api_version": "0.1.0",
        "schema_version": 4,
        "capabilities": [],
    }
    e2e_response = {
        "ready": True,
        "manifest_digest": production["manifest_digest"],
        "e2e_manifest_digest": e2e["manifest_digest"],
        "control_protocol": "arkhai.hosted-settlement-e2e-control.v0",
        "capabilities": [],
    }
    with pytest.raises(module.ReleaseVerificationError, match="control_protocol"):
        module.verify_ready_response(
            production,
            response,
            e2e=e2e,
            e2e_response=e2e_response,
        )
