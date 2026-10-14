"""Render each end-to-end lane's stack, and the full local stack, with Compose."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

# Each stack: its environment target, its compose project, and its files.
STACKS = {
    "vm": (
        "e2e-vms-dev-env",
        "simple-market-service",
        ("compose.vms.yml", "compose.vms-local.yml"),
    ),
    "apicredits": (
        "e2e-apicredits-dev-env",
        "simple-market-apicredits",
        (
            "compose.apicredits.yml",
            "compose.apicredits-local.yml",
            "compose.apicredits-lane.yml",
        ),
    ),
    "bare-metal": (
        "e2e-bare-metal-dev-env",
        "simple-market-bare-metal",
        ("compose.bare-metal.yml", "compose.dev.yml", "compose.bare-metal-local.yml"),
    ),
    "full": (
        "e2e-dev-identities-env",
        "simple-market-full",
        ("docker-compose.yml", "compose.vms-local.yml", "compose.apicredits-local.yml"),
    ),
}

API_CREDIT_SERVICES = {
    "api-credits-registry",
    "credits-service",
    "credits-storefront",
    "sample-app",
    "credits-buyer-cli",
}

# Names a storefront would read a provisioning mode under; none may reach one.
PROVISIONING_MODE_NAMES = {
    "ARKHAI_PROVISIONING_MODE",
    "MOCK_PROVISIONING_SUCCESS",
    "PROVISIONING_MODE",
}


def _compose() -> list[str]:
    binary = os.environ.get("E2E_COMPOSE_BINARY")
    command = [binary] if binary else ["docker", "compose"]
    if not shutil.which(command[0]):
        pytest.skip("Docker Compose is required for deployment rendering")
    return command


def _environment(target: str, mode: str | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("PROVISIONING_MODE", None)
    if mode is not None:
        env["PROVISIONING_MODE"] = mode
    return subprocess.run(
        ["make", "-s", "--no-print-directory", target],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def _render(tmp_path: Path, stack: str, mode: str | None = None) -> dict:
    command = _compose()
    target, project, files = STACKS[stack]
    # The targets emit only committed deterministic development credentials.
    produced = _environment(target, mode)
    assert produced.returncode == 0, produced.stderr
    env_file = tmp_path / f"{stack}.env"
    env_file.write_text(produced.stdout)
    command += ["--env-file", str(env_file), "-p", project, "--profile", "buyer"]
    for name in files:
        command += ["-f", name]
    result = subprocess.run(
        [*command, "config", "--format", "json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_the_vm_lane_composes_no_api_credit_service(tmp_path: Path) -> None:
    services = set(_render(tmp_path, "vm")["services"])
    assert {"registry", "registry-b", "bob-storefront", "alice-storefront"} <= services
    assert {"provisioning", "alice-provisioning", "buyer-cli", "anvil"} <= services
    assert not services & API_CREDIT_SERVICES
    assert "compute-registry" not in services


def test_the_api_credit_lane_composes_its_own_compute_registry(tmp_path: Path) -> None:
    services = _render(tmp_path, "apicredits")["services"]
    assert set(services) == API_CREDIT_SERVICES | {"anvil", "compute-registry"}
    registry = services["compute-registry"]
    environment = registry["environment"]
    assert environment["REGISTRY_AUTHORITY_ID"] == "compute-registry"
    assert environment["REGISTRY_DESCRIPTOR_BASE_URL"] == "http://compute-registry:8080"
    # Reached on the lane's network only.
    assert not registry.get("ports")
    mounts = {v["target"]: v["source"] for v in registry["volumes"]}
    assert mounts["/run/secrets/arkhai/registry-identity/credential"] == str(
        REPO_ROOT / "dev-env/identities/registry-a.eip191"
    )
    # Without its key the storefront publishes and negotiates but cannot settle.
    storefront = services["credits-storefront"]["environment"]
    assert storefront["APICREDITS_STOREFRONT_WALLET__PRIVATE_KEY"].startswith("@str 0x")


def test_the_full_stack_has_one_chain_and_no_lane_registry(tmp_path: Path) -> None:
    model = _render(tmp_path, "full")
    services = set(model["services"])
    assert API_CREDIT_SERVICES <= services
    assert {"registry", "bob-storefront", "alice-storefront"} <= services
    assert "compute-registry" not in services
    assert [name for name, service in model["services"].items()
            if service.get("container_name") == "anvil"] == ["anvil"]


@pytest.mark.parametrize("mode, profiles", [(None, "mock"), ("mock", "mock"), ("real", "docker")])
@pytest.mark.parametrize("stack", ["vm", "full"])
def test_vm_provisioning_follows_the_run_mode(
    tmp_path: Path, stack: str, mode: str | None, profiles: str
) -> None:
    services = _render(tmp_path, stack, mode)["services"]
    for name in ("provisioning", "alice-provisioning"):
        assert services[name]["environment"]["ACTIVE_PROFILES"] == profiles


@pytest.mark.parametrize("stack", sorted(STACKS))
def test_no_storefront_carries_a_provisioning_mode(tmp_path: Path, stack: str) -> None:
    services = _render(tmp_path, stack)["services"]
    storefronts = [name for name in services if "storefront" in name]
    assert storefronts
    for name in storefronts:
        assert not set(services[name].get("environment") or {}) & PROVISIONING_MODE_NAMES, name


@pytest.mark.parametrize(
    "target", ["e2e-vms-dev-env", "e2e-bare-metal-dev-env", "e2e-dev-identities-env"]
)
def test_an_unknown_provisioning_mode_fails_the_environment_target(target: str) -> None:
    produced = _environment(target, "hosted")
    assert produced.returncode != 0
    assert "PROVISIONING_MODE must be mock or real" in produced.stderr
