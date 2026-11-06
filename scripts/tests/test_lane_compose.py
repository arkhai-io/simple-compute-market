"""Render each end-to-end lane's stack, and the full local stack, with Compose."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DOUBLE_FIXTURES = REPO_ROOT / "tools/payments-lane-double/fixtures"
LANE_CA = REPO_ROOT / "tools/payments-lane-double/tls/lane-ca.pem"
REGISTRY_PROFILES = REPO_ROOT / "dev-env/registry"

# Each stack: its compose project and its files, in the order e2e-tests/Makefile
# layers them. No stack reads an environment file.
STACKS = {
    "vm": (
        "simple-market-service",
        (
            "compose.vms.yml",
            "compose.vms-local.yml",
            "compose.payments-double.yml",
            "compose.vms-lane.yml",
        ),
    ),
    "apicredits": (
        "simple-market-apicredits",
        (
            "compose.apicredits.yml",
            "compose.apicredits-local.yml",
            "compose.payments-double.yml",
            "compose.apicredits-lane.yml",
        ),
    ),
    "bare-metal": (
        "simple-market-bare-metal",
        (
            "compose.bare-metal.yml",
            "compose.dev.yml",
            "compose.payments-double.yml",
            "compose.bare-metal-local.yml",
        ),
    ),
    "full": (
        "simple-market-full",
        ("docker-compose.yml", "compose.vms-local.yml", "compose.apicredits-local.yml"),
    ),
}

# Each base file, which composes topology alone.
BASE_FILES = ("compose.vms.yml", "compose.apicredits.yml", "compose.bare-metal.yml", "docker-compose.yml")

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


def _render_files(project: str, files: tuple[str, ...], mode: str | None = None) -> dict:
    """Render ``files`` from the repository root with no environment file; the
    one variable the stacks read, PROVISIONING_MODE, is ``mode`` or unset."""
    env = dict(os.environ)
    env.pop("PROVISIONING_MODE", None)
    if mode is not None:
        env["PROVISIONING_MODE"] = mode
    command = [*_compose(), "-p", project, "--profile", "buyer"]
    for name in files:
        command += ["-f", name]
    result = subprocess.run(
        [*command, "config", "--format", "json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _render(stack: str, mode: str | None = None) -> dict:
    project, files = STACKS[stack]
    return _render_files(project, files, mode)


def _mounts(service: dict) -> dict[str, str]:
    return {v["target"]: v["source"] for v in service.get("volumes", [])}


def test_the_vm_lane_composes_no_api_credit_service() -> None:
    services = set(_render("vm")["services"])
    assert {"registry", "registry-b", "bob-storefront", "alice-storefront"} <= services
    assert {"provisioning", "alice-provisioning", "buyer-cli", "anvil"} <= services
    assert not services & API_CREDIT_SERVICES
    assert "compute-registry" not in services


def test_the_api_credit_lane_composes_its_own_compute_registry() -> None:
    services = _render("apicredits")["services"]
    assert set(services) == API_CREDIT_SERVICES | {"anvil", "compute-registry", "payments-double"}
    registry = services["compute-registry"]
    environment = registry["environment"]
    assert environment["CONFIG_DIRECTORY"] == "/etc/arkhai/registry"
    assert environment["ACTIVE_PROFILES"] == "compute-registry,payments-lane"
    # Reached on the lane's network only.
    assert not registry.get("ports")
    mounts = _mounts(registry)
    assert mounts["/etc/arkhai/registry"] == str(REGISTRY_PROFILES)
    assert mounts["/run/secrets/arkhai/registry-identity/credential"] == str(
        REPO_ROOT / "dev-env/identities/registry-a.eip191"
    )
    # Without its wallet key the storefront publishes and negotiates but cannot
    # settle; the key is in its secret overlay, not its environment.
    storefront = services["credits-storefront"]
    assert not {
        name for name in storefront.get("environment") or {} if "PRIVATE_KEY" in name
    }
    assert _mounts(storefront)["/etc/arkhai/storefront.secrets.toml"] == str(
        REPO_ROOT / "dev-env/identities/api-credits.storefront.secrets.toml"
    )


def test_the_full_stack_has_one_chain_and_no_lane_registry() -> None:
    model = _render("full")
    services = set(model["services"])
    assert API_CREDIT_SERVICES <= services
    assert {"registry", "bob-storefront", "alice-storefront"} <= services
    assert "compute-registry" not in services
    assert [name for name, service in model["services"].items()
            if service.get("container_name") == "anvil"] == ["anvil"]


@pytest.mark.parametrize("mode, last", [(None, "mock"), ("mock", "mock"), ("real", "real")])
@pytest.mark.parametrize("stack", ["vm", "full"])
def test_vm_provisioning_takes_its_site_profile_then_the_run_mode(
    stack: str, mode: str | None, last: str
) -> None:
    services = _render(stack, mode)["services"]
    for name, site in (("provisioning", "vms-bob-site"), ("alice-provisioning", "vms-alice-site")):
        environment = services[name]["environment"]
        assert environment["CONFIG_DIRECTORY"] == "/app/config"
        assert environment["ACTIVE_PROFILES"] == f"docker,{site},{last}"
        assert not {key for key in environment if key.startswith("PROVISIONING_")} - {
            "PROVISIONING_DATABASE_URL", "PROVISIONING_STOREFRONT_URL",
        }, name


@pytest.mark.parametrize("stack", sorted(STACKS))
def test_no_storefront_carries_a_provisioning_mode(stack: str) -> None:
    services = _render(stack)["services"]
    storefronts = [name for name in services if "storefront" in name]
    assert storefronts
    for name in storefronts:
        assert not set(services[name].get("environment") or {}) & PROVISIONING_MODE_NAMES, name


@pytest.mark.parametrize("stack", sorted(STACKS))
def test_no_storefront_reads_a_secret_from_its_environment(stack: str) -> None:
    """A storefront's environment carries its configuration directory and its
    signing credential, kept from the loader; every secret setting is in its
    mounted secret overlay."""
    services = _render(stack)["services"]
    for name, service in services.items():
        if "storefront" not in name:
            continue
        environment = set(service.get("environment") or {})
        assert environment <= {"XDG_CONFIG_HOME", "PYTHONPATH", "ARKHAI_IDENTITY_CREDENTIAL"}, name
        assert "/etc/arkhai/storefront.secrets.toml" in _mounts(service), name


# Each lane's payment storefront, the configuration it mounts and its settlement
# table's key, and the registries its listings reach.
PAYMENT_LANES = {
    "vm": (
        "bob-storefront", "domains/vms/storefront/storefront.bob.lane.toml", "Settlement",
        ("registry", "registry-b"),
    ),
    "apicredits": (
        "credits-storefront", "domains/apicredits/storefront/storefront.credits.lane.toml",
        "settlement", ("api-credits-registry", "compute-registry"),
    ),
    "bare-metal": (
        "bare-metal-storefront", "domains/bare_metal/storefront/storefront.dev.toml",
        "Settlement", ("bare-metal-registry",),
    ),
}


@pytest.mark.parametrize("stack", sorted(PAYMENT_LANES))
def test_each_lane_settles_against_its_payments_double(stack: str) -> None:
    """The lane runs the double with no host port; its payment storefront mounts
    its lane configuration and the lane CA at the path that configuration trusts;
    and its registries layer the lane profile recommending the pinned dispute
    authority."""
    services = _render(stack)["services"]
    storefront_name, configuration, settlement, registries = PAYMENT_LANES[stack]
    double = services["payments-double"]
    assert double["image"] == "arkhai:payments-lane-double"
    assert not double.get("ports")

    storefront = services[storefront_name]
    assert storefront["depends_on"]["payments-double"]["condition"] == "service_healthy"
    mounts = _mounts(storefront)
    assert mounts["/etc/arkhai/storefront.toml"] == str(REPO_ROOT / configuration)
    payments = tomllib.loads((REPO_ROOT / configuration).read_text(encoding="utf-8"))[settlement][
        "arkhai_payments"
    ]
    assert mounts[payments["ca_bundle_path"]] == str(LANE_CA)

    for name in registries:
        environment = services[name]["environment"]
        assert environment["CONFIG_DIRECTORY"] == "/etc/arkhai/registry", name
        assert environment["ACTIVE_PROFILES"].split(",")[-1] == "payments-lane", name
        assert _mounts(services[name])["/etc/arkhai/registry"] == str(REGISTRY_PROFILES), name


def test_the_full_stack_runs_no_payments_double() -> None:
    services = _render("full")["services"]
    assert "payments-double" not in services
    for name, configuration in (
        ("bob-storefront", "domains/vms/storefront/storefront.bob.toml"),
        ("credits-storefront", "domains/apicredits/storefront/storefront.credits.toml"),
    ):
        mounts = _mounts(services[name])
        assert mounts["/etc/arkhai/storefront.toml"] == str(REPO_ROOT / configuration), name
        assert str(LANE_CA) not in mounts.values(), name
    for name in ("registry", "registry-b", "api-credits-registry"):
        assert "payments-lane" not in services[name]["environment"]["ACTIVE_PROFILES"], name


# A bind of one of these is a deployment's own, which only an overlay may make.
_DEVELOPMENT_SOURCES = (
    REPO_ROOT / "dev-env",
    REPO_ROOT / "tools",
    REPO_ROOT / "kit",
    REPO_ROOT / "provisioning",
    REPO_ROOT / ".e2e-buyer",
)


@pytest.mark.parametrize("files", BASE_FILES)
def test_a_base_file_renders_alone_with_no_development_bind(files: str) -> None:
    """A base file needs no variable to render, and binds no credential,
    configuration file, profile or definition document: without an overlay its
    services have nothing to fall back on."""
    services = _render_files("simple-market-base", (files,))["services"]
    for name, service in services.items():
        environment = service.get("environment") or {}
        assert "ARKHAI_IDENTITY_CREDENTIAL" not in environment, name
        assert not {key for key in environment if key.startswith("REGISTRY_AUTHORITY")}, name
        for source in _mounts(service).values():
            path = Path(source)
            assert not any(path.is_relative_to(root) for root in _DEVELOPMENT_SOURCES), (name, source)
            assert path.suffix not in {".toml", ".env", ".eip191", ".ed25519"}, (name, source)


@pytest.mark.parametrize(
    "target", ["e2e-vms-dev-env", "e2e-bare-metal-dev-env", "e2e-dev-identities-env"]
)
def test_an_unknown_provisioning_mode_fails_the_environment_target(target: str) -> None:
    env = {**os.environ, "PROVISIONING_MODE": "hosted"}
    produced = subprocess.run(
        ["make", "-s", "--no-print-directory", target],
        cwd=REPO_ROOT, capture_output=True, text=True, env=env,
    )
    assert produced.returncode != 0
    assert "PROVISIONING_MODE must be mock or real" in produced.stderr
