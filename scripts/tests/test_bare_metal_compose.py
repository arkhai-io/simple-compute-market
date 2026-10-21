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
    tmp_path: Path, development: bool, mode: str
) -> None:
    compose_binary = os.environ.get("E2E_COMPOSE_BINARY")
    command = [compose_binary] if compose_binary else ["docker", "compose"]
    if not shutil.which(command[0]):
        pytest.skip("Docker Compose is required for deployment rendering")
    # The target emits only committed deterministic development credentials.
    env_file = tmp_path / "development.env"
    with env_file.open("w") as output:
        subprocess.run(
            ["make", "-s", "--no-print-directory", "e2e-bare-metal-dev-env"],
            cwd=REPO_ROOT,
            stdout=output,
            check=True,
            env={**os.environ, "PROVISIONING_MODE": mode},
        )
    command += [
        "--env-file", str(env_file), "-p", "bare-metal-render",
        "--profile", "buyer", "-f", "compose.bare-metal.yml",
    ]
    if development:
        command += ["-f", "compose.dev.yml", "-f", "compose.bare-metal-local.yml"]
    result = subprocess.run(
        [*command, "config", "--format", "json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    model = json.loads(result.stdout)
    services = model["services"]
    expected = {
        "bare-metal-registry", "bare-metal-redis", "bare-metal-provisioning",
        "bare-metal-storefront", "bare-metal-buyer",
    }
    assert set(services) == expected | ({"anvil"} if development else set())
    provisioning = services["bare-metal-provisioning"]
    # The run's provisioning mode selects the site's profile, with or without
    # the development overlay.
    assert provisioning["environment"]["ACTIVE_PROFILES"] == (
        "mock" if mode == "mock" else "docker"
    )
    mounts = {v["target"]: v["source"] for v in provisioning["volumes"]}
    # Bare metal's stack needs nothing from another domain's tree.
    assert "/opt/domains/vms/provisioning/iac" not in mounts
    assert mounts["/opt/domains/bare_metal/provisioning/iac"] == str(
        REPO_ROOT / "domains/bare_metal/provisioning/iac"
    )
    registry = services["bare-metal-registry"]
    assert registry["environment"]["REGISTRY_AUTHORITY_ID"] == "bare-metal-registry"
    mounts = {v["target"]: v["source"] for v in registry["volumes"]}
    assert mounts["/app/shared-env"] == str(REPO_ROOT / "shared-env")
    assert mounts["/run/secrets/arkhai/registry-identity/credential"] == str(
        REPO_ROOT / "dev-env/identities/registry-a.eip191"
    )
    for service in services.values():
        for volume in service.get("volumes", []):
            if volume["type"] == "volume":
                assert volume["source"] in model["volumes"]
    storefront = services["bare-metal-storefront"]
    # Every storefront setting is in a mounted file: the environment carries
    # only the configuration directory and the signer credential, with or
    # without the development overlay.
    assert set(storefront["environment"]) == {"XDG_CONFIG_HOME", "ARKHAI_IDENTITY_CREDENTIAL"}
    assert storefront["environment"]["XDG_CONFIG_HOME"] == "/etc"
    mounts = {v["target"]: v["source"] for v in storefront["volumes"]}
    assert mounts["/etc/arkhai/storefront.toml"] == str(
        REPO_ROOT / "domains/bare_metal/storefront/storefront.dev.toml"
    )
    assert mounts["/etc/arkhai/storefront.secrets.toml"] == str(
        REPO_ROOT / "dev-env/identities/bare-metal.storefront.secrets.toml"
    )
    if development:
        assert storefront["depends_on"]["anvil"]["condition"] == "service_healthy"
        # The address book the development storefront.toml names.
        assert mounts["/app/alkahest_anvil_addresses.json"] == str(
            REPO_ROOT / "kit/alkahest/src/market_alkahest/data/alkahest_anvil_addresses.json"
        )
    else:
        assert "/app/alkahest_anvil_addresses.json" not in mounts
