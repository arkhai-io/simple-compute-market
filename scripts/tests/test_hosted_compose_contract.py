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
    assert '"127.0.0.1:${HOSTED_STOREFRONT_HOST_PORT:-18081}:8001"' in COMPOSE
    assert 'base_url = "http://127.0.0.1:8080"' in (
        REPO_ROOT / "e2e-tests" / "config" / "hosted-storefront.toml"
    ).read_text(encoding="utf-8")
    assert "network_mode: service:hosted-settlement-api" in COMPOSE
    assert "aliases: [bob-storefront]" in COMPOSE


def test_compose_contains_only_ordinary_hosted_roles() -> None:
    for service in (
        "hosted-settlement-migrate:",
        "hosted-settlement-api:",
        "hosted-settlement-worker:",
    ):
        assert service in COMPOSE
    for retired in (
        "hosted-settlement-simulator",
        "hosted-settlement-control",
        "hosted-settlement-admit-fixture",
        "hosted-settlement-event-worker",
        "hosted-compose-control",
        "hosted-e2e-runner",
        "hosted-hermetic",
        "controlled-clock",
        "controlled-events",
    ):
        assert retired not in COMPOSE
    assert 'command: ["hosted-settlement-migrate"]' in COMPOSE
    assert 'command: ["hosted-settlement-api"' in COMPOSE
    assert 'command: ["hosted-settlement-worker"' in COMPOSE


def test_compose_has_no_source_or_editable_sibling_mount() -> None:
    lowered = COMPOSE.lower()
    assert "../hosted-settlement" not in lowered
    assert "editable" not in lowered
    assert "/src" not in lowered
    assert "source: ${HOSTED_SETTLEMENT_VERIFIED_RELEASE_DIR" in COMPOSE
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


def test_only_hosted_service_secret_environment_is_required() -> None:
    assert "HOSTED_SETTLEMENT_ENV_FILE:?" in COMPOSE
    assert "HOSTED_SETTLEMENT_E2E" not in COMPOSE
    preparer = (REPO_ROOT / "scripts" / "prepare-hosted-compose.py").read_text(
        encoding="utf-8"
    )
    for token in ("SECRET", "TOKEN", "CREDENTIAL", "PRIVATE_KEY", "WEBHOOK"):
        assert token in preparer


def test_clean_and_restart_targets_have_opposite_volume_behavior() -> None:
    restart = ROOT_MAKE.split("hosted-compose-restart:", 1)[1].split(
        "hosted-compose-clean:", 1
    )[0]
    clean = ROOT_MAKE.split("hosted-compose-clean:", 1)[1].split(
        "hosted-stripe-test:", 1
    )[0]
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


def test_only_production_and_protected_stripe_targets_exist() -> None:
    for target in (
        "hosted-preflight:",
        "hosted-compose-start:",
        "hosted-compose-restart:",
        "hosted-compose-clean:",
        "hosted-stripe-test:",
    ):
        assert target in ROOT_MAKE
    for retired in (
        "hosted-hermetic-preflight:",
        "hosted-hermetic:",
        "hosted-local-eas:",
        "build-hosted:",
        "hosted-real-stripe:",
    ):
        assert retired not in ROOT_MAKE
        assert retired not in E2E_MAKE


def test_active_composition_has_no_fixture_or_simulator_selector() -> None:
    surfaces = (
        REPO_ROOT / "Makefile",
        REPO_ROOT / "compose.hosted-settlement.yml",
        REPO_ROOT / "e2e-tests" / "Dockerfile",
        REPO_ROOT / "e2e-tests" / "Makefile",
        REPO_ROOT / "scripts" / "prepare-hosted-compose.py",
        REPO_ROOT / "scripts" / "verify-hosted-release.py",
    )
    forbidden = (
        "arkhai_hosted_settlement_e2e",
        "HOSTED_E2E_FIXTURE",
        "HOSTED_E2E_MANIFEST",
        "hosted-hermetic",
        "hosted-settlement-simulator",
        "hosted-settlement-control",
        "hosted-settlement-event-worker",
        "controlled-clock",
        "controlled-events",
        "e2e-fixture-wheel",
        "e2e-manifest",
        "verify_hermetic_release",
    )
    for path in surfaces:
        content = path.read_text(encoding="utf-8")
        assert not set(forbidden).intersection(content.split())
        for token in forbidden:
            assert token not in content, (
                f"{path.relative_to(REPO_ROOT)} contains {token}"
            )


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


def test_marketplace_hosted_configs_contain_no_provider_fixture_identity() -> None:
    for filename in ("hosted-storefront.toml", "hosted-buyer.toml"):
        content = (REPO_ROOT / "e2e-tests" / "config" / filename).read_text(
            encoding="utf-8"
        )
        for forbidden in (
            "fixture-account",
            "account_ref",
            "connected_account",
            "provider_credential",
            "webhook_secret",
            "control_url",
        ):
            assert forbidden not in content


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
