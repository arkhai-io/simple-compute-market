"""Render the bare-metal operator stack and its development overlay with Compose."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("mode", ["mock", "real"])
@pytest.mark.parametrize("development", [False, True])
def test_bare_metal_compose_merges_bindings_and_preserves_mount_paths(
    development: bool, mode: str
) -> None:
    compose_binary = os.environ.get("E2E_COMPOSE_BINARY")
    command = [compose_binary] if compose_binary else ["docker", "compose"]
    if not shutil.which(command[0]):
        pytest.skip("Docker Compose is required for deployment rendering")
    # No environment file: the run's provisioning mode is the one variable read.
    command += ["-p", "bare-metal-render", "--profile", "buyer", "-f", "compose.bare-metal.yml"]
    if development:
        command += [
            "-f", "compose.dev.yml", "-f", "compose.payments-double.yml",
            "-f", "compose.bare-metal-local.yml",
        ]
    result = subprocess.run(
        [*command, "config", "--format", "json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PROVISIONING_MODE": mode},
    )
    model = json.loads(result.stdout)
    services = model["services"]
    expected = {
        "bare-metal-registry", "bare-metal-redis", "bare-metal-provisioning",
        "bare-metal-storefront",
    }
    assert set(services) == expected | (
        {"anvil", "mailpit", "payments-double", "bare-metal-buyer"} if development else set()
    )
    provisioning = services["bare-metal-provisioning"]
    # The base file runs real provisioning; the development overlay appends the
    # site's profile and the run's mode.
    assert provisioning["environment"]["ACTIVE_PROFILES"] == (
        f"docker,bare-metal-site,{mode}" if development else "docker"
    )
    mounts = {v["target"]: v["source"] for v in provisioning["volumes"]}
    # Bare metal's stack needs nothing from another domain's tree.
    assert "/opt/domains/vms/provisioning/iac" not in mounts
    assert mounts["/opt/domains/bare_metal/provisioning/iac"] == str(
        REPO_ROOT / "domains/bare_metal/provisioning/iac"
    )
    definitions = {
        "/run/config/host-definitions.yaml": "dev-env/bare-metal/hosts.yaml",
        "/run/config/resource-pools.yaml": "dev-env/bare-metal/resource-pools.yaml",
        "/app/config/config-bare-metal-site.yml": "dev-env/provisioning/config-bare-metal-site.yml",
    }
    for target, source in definitions.items():
        # Only the deployment's overlay names a definition document or profile.
        assert mounts.get(target) == (str(REPO_ROOT / source) if development else None)
    registry = services["bare-metal-registry"]
    environment = registry["environment"]
    assert environment["DATABASE_URL"] == "sqlite:////app/data/indexer.db"
    assert environment.get("ACTIVE_PROFILES") == (
        "bare-metal-registry,payments-lane" if development else None
    )
    assert not {key for key in environment if key.startswith("REGISTRY_")}
    mounts = {v["target"]: v["source"] for v in registry["volumes"]}
    assert mounts["/app/shared-env"] == str(REPO_ROOT / "shared-env")
    assert mounts.get("/run/secrets/arkhai/registry-identity/credential") == (
        str(REPO_ROOT / "dev-env/identities/registry-a.eip191") if development else None
    )
    for service in services.values():
        for volume in service.get("volumes", []):
            if volume["type"] == "volume":
                assert volume["source"] in model["volumes"]
    storefront = services["bare-metal-storefront"]
    # Every storefront setting is in a mounted file: the environment carries
    # only the configuration directory and, from the overlay's identity file,
    # the signer credential.
    assert set(storefront["environment"]) == {"XDG_CONFIG_HOME"} | (
        {"ARKHAI_IDENTITY_CREDENTIAL"} if development else set()
    )
    assert storefront["environment"]["XDG_CONFIG_HOME"] == "/etc"
    mounts = {v["target"]: v["source"] for v in storefront["volumes"]}
    if development:
        assert mounts["/etc/arkhai/storefront.toml"] == str(
            REPO_ROOT / "domains/bare_metal/storefront/storefront.dev.toml"
        )
        assert mounts["/etc/arkhai/storefront.secrets.toml"] == str(
            REPO_ROOT / "dev-env/identities/bare-metal.storefront.secrets.toml"
        )
        assert storefront["depends_on"]["anvil"]["condition"] == "service_healthy"
        # The mail sink the development storefront.toml's seller delivery names.
        assert storefront["depends_on"]["mailpit"]["condition"] == "service_healthy"
        # The payments double the development storefront.toml settles against.
        assert storefront["depends_on"]["payments-double"]["condition"] == "service_healthy"
        # The address book the development storefront.toml names.
        assert mounts["/app/alkahest_anvil_addresses.json"] == str(
            REPO_ROOT / "kit/alkahest/src/market_alkahest/data/alkahest_anvil_addresses.json"
        )
    else:
        assert set(mounts) == {"/var/lib/arkhai"}
