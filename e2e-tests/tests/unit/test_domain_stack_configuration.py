"""Static stack contracts that protect role and package boundaries."""

from __future__ import annotations

import re
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


_PIN = re.compile(r"(arkhai-[a-z0-9-]+)(?:\[[a-z0-9,_-]+\])?==([0-9][0-9a-z.+-]*)")


def _declared_versions() -> dict[str, str]:
    """Every repository-owned distribution's name and declared version."""
    versions: dict[str, str] = {}
    for pyproject in _REPO_ROOT.rglob("pyproject.toml"):
        if any(part in {".venv", "node_modules", "build"} for part in pyproject.parts):
            continue
        project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
        if str(project.get("name", "")).startswith("arkhai-") and "version" in project:
            versions[project["name"]] = project["version"]
    return versions


def test_every_image_pins_the_version_its_package_declares():
    """An image's pin of a repository-owned package must name the version the
    repository builds.

    Images install from the staged wheelhouse *and* a public index. A pin the
    wheelhouse cannot satisfy therefore does not fail the build: the resolver
    fetches that version from the index instead, together with that release's
    own dependency pins, and the image runs code other than the source being
    tested. Checking every pin against its package's declared version turns
    that silent substitution into a failure here.
    """
    declared = _declared_versions()
    stale = []
    pinned = 0
    for dockerfile in _REPO_ROOT.rglob("Dockerfile*"):
        if any(part in {".venv", "node_modules"} for part in dockerfile.parts):
            continue
        text = dockerfile.read_text(encoding="utf-8", errors="replace")
        for name, version in _PIN.findall(text):
            if name not in declared:
                continue
            pinned += 1
            if declared[name] != version:
                stale.append(
                    f"{dockerfile.relative_to(_REPO_ROOT)}: {name}=={version}, "
                    f"but the package declares {declared[name]}"
                )
    assert pinned, "no image pins were found; the pattern no longer matches"
    assert not stale, "\n".join(stale)
