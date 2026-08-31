"""Static stack contracts that protect role and package boundaries."""

from __future__ import annotations

import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_api_credit_stack_has_no_committed_admin_credential():
    compose = (_REPO_ROOT / "domains/apicredits/compose.yml").read_text(
        encoding="utf-8"
    )
    storefront = (
        _REPO_ROOT / "domains/apicredits/storefront/storefront.credits.toml"
    ).read_text(encoding="utf-8")

    assert "test-api-key" not in compose + storefront
    assert "${APICREDITS_ADMIN_KEY_FILE:?" in compose
    assert compose.count("/run/secrets/arkhai/api-credits-admin-key:ro") == 3
    assert 'admin_key_file      = "/run/secrets/arkhai/api-credits-admin-key"' in storefront


def test_api_credit_state_uses_independent_named_volumes():
    compose = (_REPO_ROOT / "domains/apicredits/compose.yml").read_text(
        encoding="utf-8"
    )

    assert "api-credits-service-data:/app/data" in compose
    assert "api-credits-storefront-data:/app/data" in compose
    assert "api-credits-service-data:" in compose
    assert "api-credits-storefront-data:" in compose


def test_api_credit_storefront_runtime_uses_staged_wheel_only():
    """The image installs the wheel its own project declares, and only that.

    The version is read rather than written down. A literal here asserts a
    number the project has already moved past, and a guard that has to be
    edited alongside the thing it guards eventually stops guarding it.
    """

    storefront = _REPO_ROOT / "domains/apicredits/storefront"
    dockerfile = (storefront / "Dockerfile").read_text(encoding="utf-8")
    declared = tomllib.loads((storefront / "pyproject.toml").read_text(encoding="utf-8"))
    version = declared["project"]["version"]

    assert f"arkhai-apicredits-storefront=={version}" in dockerfile
    assert "COPY domains/apicredits/storefront/src" not in dockerfile
    assert 'ENV PYTHONPATH="/app"' not in dockerfile


def test_bare_metal_stack_requires_real_selected_site_inputs():
    domain_compose = (_REPO_ROOT / "domains/bare_metal/compose.yml").read_text(
        encoding="utf-8"
    )
    wrapper = (_REPO_ROOT / "compose.bare-metal.yml").read_text(encoding="utf-8")
    rendered = domain_compose + wrapper

    assert "arkhai:bare-metal-storefront" in domain_compose
    assert "ACTIVE_PROFILES=docker" in domain_compose
    assert "ACTIVE_PROFILES=mock" not in rendered
    assert "MOCK_PROVISIONING" not in rendered
    assert "${BARE_METAL_STOREFRONT_SITES_JSON:?" in domain_compose
    assert "${BARE_METAL_POOL_DEFINITIONS_FILE:?" in domain_compose
    assert "${BARE_METAL_PROVISIONING_INVENTORY_FILE:?" in domain_compose
    assert "${BARE_METAL_PROVISIONING_SSH_PRIVATE_KEY_FILE:?" in domain_compose


def test_bare_metal_stack_keeps_role_credentials_and_state_separate():
    domain_compose = (_REPO_ROOT / "domains/bare_metal/compose.yml").read_text(
        encoding="utf-8"
    )
    wrapper = (_REPO_ROOT / "compose.bare-metal.yml").read_text(encoding="utf-8")

    assert "ARKHAI_IDENTITY_CREDENTIAL=" not in wrapper
    assert "BARE_METAL_REGISTRY_IDENTITY_CREDENTIAL_FILE:?" in wrapper
    assert "BARE_METAL_STOREFRONT_IDENTITY_ENV_FILE:?" in wrapper
    assert "BARE_METAL_PROVISIONING_IDENTITY_ENV_FILE:?" in wrapper
    for name in (
        "bare-metal-registry-data",
        "bare-metal-redis-data",
        "bare-metal-provisioning-data",
        "bare-metal-storefront-data",
    ):
        assert f"{name}:" in domain_compose
