"""Render the bare-metal operator stack and its development overlay with Compose."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("development", [False, True])
def test_bare_metal_compose_merges_bindings_and_preserves_mount_paths(
    tmp_path: Path, development: bool
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
    assert provisioning["environment"]["ACTIVE_PROFILES"] == (
        "mock" if development else "docker"
    )
    mounts = {v["target"]: v["source"] for v in provisioning["volumes"]}
    assert mounts["/opt/domains/vms/provisioning/iac"] == str(
        REPO_ROOT / "domains/vms/provisioning/iac"
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
    if development:
        assert services["bare-metal-storefront"]["depends_on"]["anvil"]["condition"] == "service_healthy"
