"""Hold every value a stack's committed files restate to the file it restates.

The development stacks take their configuration from committed overlays,
registry and site profiles, and secret overlays, and several of those restate a
value whose source is another file: a registry's or site's pinned identity, the
key that signs as it; a storefront's payments key, the payments double's
fixtures; the lanes' recommended dispute authority, the double's pinned one; a
storefront's CA bundle path, where its overlay binds the lane CA. Each test here
fails naming both sides when one drifts. Every value involved is a public
development value, never for a public network.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib

from market_identity import create_signer
import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DOUBLE_FIXTURES = REPO_ROOT / "tools/payments-lane-double/fixtures"
IDENTITIES = REPO_ROOT / "dev-env/identities"
REGISTRY_PROFILES = REPO_ROOT / "dev-env/registry"
RUNNER_PINS = REPO_ROOT / "e2e-tests/config/config-docker.yml"
LANE_CA = REPO_ROOT / "tools/lane-double-controls/tls/lane-ca.pem"

# Each stack's files, in the order e2e-tests/Makefile layers them.
STACKS = {
    "vm": ("compose.vms.yml", "compose.vms-local.yml", "compose.payments-double.yml",
           "compose.vms-lane.yml"),
    "apicredits": ("compose.apicredits.yml", "compose.apicredits-local.yml",
                   "compose.payments-double.yml", "compose.apicredits-lane.yml"),
    "bare-metal": ("compose.bare-metal.yml", "compose.dev.yml", "compose.payments-double.yml",
                   "compose.bare-metal-local.yml"),
    "full": ("docker-compose.yml", "compose.vms-local.yml", "compose.apicredits-local.yml"),
}
# Every overlay, which alone may bind a committed development file.
OVERLAYS = (
    "compose.vms-local.yml", "compose.vms-lane.yml", "compose.apicredits-local.yml",
    "compose.apicredits-lane.yml", "compose.bare-metal-local.yml", "compose.payments-double.yml",
)
# The Git-ignored buyer runtime directories, which a buyer service's operator
# creates before running it; every other bind source is committed.
RUNTIME_DIRECTORY = "./.e2e-buyer/"
REGISTRY_CREDENTIAL = "/run/secrets/arkhai/registry-identity/credential"


def _render(stack: str) -> dict:
    binary = os.environ.get("E2E_COMPOSE_BINARY")
    command = [binary] if binary else ["docker", "compose"]
    if not shutil.which(command[0]):
        pytest.skip("Docker Compose is required for deployment rendering")
    for name in STACKS[stack]:
        command += ["-f", name]
    env = {key: value for key, value in os.environ.items() if key != "PROVISIONING_MODE"}
    result = subprocess.run(
        [*command, "-p", f"values-{stack}", "--profile", "buyer", "config", "--format", "json"],
        cwd=REPO_ROOT, capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["services"]


def _mounts(service: dict) -> dict[str, str]:
    return {v["target"]: v["source"] for v in service.get("volumes", [])}


def _dotenv(path: Path) -> dict[str, str]:
    """A registry profile as its dotenv reader takes it: ``KEY=value`` lines,
    a value's surrounding quotes removed, comments and blank lines skipped."""
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _identity(scheme: str, credential: str) -> dict[str, str]:
    signed = create_signer(scheme, credential.strip()).identity
    return {"scheme": str(getattr(signed.scheme, "value", signed.scheme)), "identifier": signed.identifier}


def _same_identity(stated: dict, derived: dict) -> bool:
    # An eip191 address is compared case-insensitively, as its verifier does.
    if stated["scheme"] != derived["scheme"]:
        return False
    if stated["scheme"] == "eip191":
        return stated["identifier"].lower() == derived["identifier"].lower()
    return stated["identifier"] == derived["identifier"]


# --- registry profiles ---------------------------------------------------------


@pytest.mark.parametrize("stack", sorted(STACKS))
def test_each_registry_profile_pins_the_credential_its_registry_mounts(stack: str) -> None:
    registries = {
        name: service for name, service in _render(stack).items()
        if service["image"] == "arkhai:registry"
    }
    assert registries
    for name, service in registries.items():
        environment = service["environment"]
        assert environment["CONFIG_DIRECTORY"] == "/etc/arkhai/registry", name
        directory = Path(_mounts(service)["/etc/arkhai/registry"])
        assert directory == REGISTRY_PROFILES, name
        profiles = environment["ACTIVE_PROFILES"].split(",")
        files = [directory / f"config-{profile}.env" for profile in profiles]
        assert all(path.is_file() for path in files), (name, profiles)
        own = _dotenv(files[0])
        assert own["REGISTRY_AUTHORITY_CREDENTIAL_FILE"] == REGISTRY_CREDENTIAL, name
        credential = Path(_mounts(service)[REGISTRY_CREDENTIAL]).read_text(encoding="utf-8")
        stated = {
            "scheme": own["REGISTRY_AUTHORITY_SCHEME"],
            "identifier": own["REGISTRY_AUTHORITY_IDENTIFIER"],
        }
        derived = _identity(stated["scheme"], credential)
        assert _same_identity(stated, derived), (name, files[0].name, stated, derived)


def test_the_private_registry_bootstrap_key_is_the_one_its_clients_hold() -> None:
    """registry-b seeds its bootstrap key, which Bob publishes with, the
    development buyer discovers with, and the test runner reads with."""
    seeded = _dotenv(REGISTRY_PROFILES / "config-registry-b.env")["REGISTRY_BOOTSTRAP_API_KEY"]
    url = "http://registry-b:8080"
    held = {
        "bob.storefront.secrets.toml": _toml(IDENTITIES / "bob.storefront.secrets.toml")[
            "registry"]["auth"][url],
        "buyer.config.toml": _toml(IDENTITIES / "buyer.config.toml")["registry"]["auth"][url],
        "config-docker.yml": yaml.safe_load(RUNNER_PINS.read_text(encoding="utf-8"))[
            "registry"]["bootstrap_api_key"],
    }
    assert held == dict.fromkeys(held, seeded)


def test_the_lane_profile_recommends_the_double_pinned_authority() -> None:
    recommended = _dotenv(REGISTRY_PROFILES / "config-payments-lane.env")
    authority = _toml(DOUBLE_FIXTURES / "dispute-authority.toml")
    assert set(recommended) == {"REGISTRY_DESCRIPTOR_RECOMMENDED_DISPUTE_AUTHORITIES"}
    assert json.loads(recommended["REGISTRY_DESCRIPTOR_RECOMMENDED_DISPUTE_AUTHORITIES"]) == [
        authority
    ]


# --- provisioning site profiles ------------------------------------------------

# Each provisioning service, the runner's settings section that pins it, and the
# keys of that section naming its own signer and its administrator.
_SITE_PINS = {
    "provisioning": ("provisioning", "authority", "admin"),
    "alice-provisioning": ("alice_provisioning", "authority", "admin"),
    "bare-metal-provisioning": ("bare_metal_lane", "site_authority", "site_admin"),
}


def _site_profile(service: dict) -> dict:
    environment = service["environment"]
    site = environment["ACTIVE_PROFILES"].split(",")[1]
    path = _mounts(service)[f"{environment['CONFIG_DIRECTORY']}/config-{site}.yml"]
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


@pytest.mark.parametrize("stack", ["vm", "bare-metal", "full"])
def test_each_site_profile_pins_its_signer_and_the_runner_pins_the_same(stack: str) -> None:
    runner = yaml.safe_load(RUNNER_PINS.read_text(encoding="utf-8"))
    services = _render(stack)
    sites = [name for name in _SITE_PINS if name in services]
    assert sites
    for name in sites:
        service = services[name]
        profile = _site_profile(service)
        section, authority, admin = _SITE_PINS[name]
        pins = runner[section]
        # The site's own identity is the key its environment's credential signs as.
        derived = _identity(
            profile["identity"]["scheme"], service["environment"]["ARKHAI_IDENTITY_CREDENTIAL"]
        )
        assert _same_identity(profile["identity"], derived), (name, profile["identity"], derived)
        runner_authority = {
            "scheme": pins[f"{authority}_scheme"], "identifier": pins[f"{authority}_identifier"],
        }
        assert _same_identity(profile["identity"], runner_authority), name
        runner_admin = _identity(pins[f"{admin}_scheme"], pins[f"{admin}_credential"])
        assert _same_identity(profile["admin_identity"], runner_admin), name
        if section == "bare_metal_lane":
            assert profile["storefront_site_id"] == pins["site_id"]
            assert _same_identity(
                profile["storefront_identity"],
                {"scheme": pins["storefront_scheme"], "identifier": pins["storefront_identifier"]},
            )


# --- storefront secret overlays and trust --------------------------------------

# Each storefront secret overlay holding the seller's payments key, and its
# settlement table's key.
_PAYMENTS_KEYS = {
    "bob.storefront.secrets.toml": "Settlement",
    "bare-metal.storefront.secrets.toml": "Settlement",
    "api-credits.storefront.secrets.toml": "settlement",
}


@pytest.mark.parametrize(("overlay", "settlement"), sorted(_PAYMENTS_KEYS.items()))
def test_each_secret_overlay_holds_the_double_seller_token(overlay: str, settlement: str) -> None:
    seller = _toml(DOUBLE_FIXTURES / "accounts.toml")["accounts"]["seller"]
    assert _toml(IDENTITIES / overlay)[settlement]["arkhai_payments"] == {
        "api_key": seller["token"]
    }


@pytest.mark.parametrize("stack", sorted(STACKS))
def test_each_storefront_secret_overlay_fits_the_configuration_beside_it(stack: str) -> None:
    """A storefront loads its configuration and secret overlay merged, so the
    overlay's wallet key must sign as the configuration's wallet address, and a
    payments key there admits no other key form in the configuration, enabled or
    not, since the payments section refuses two."""
    storefronts = {
        name: _mounts(service) for name, service in _render(stack).items()
        if "/etc/arkhai/storefront.secrets.toml" in _mounts(service)
    }
    assert storefronts
    for name, mounts in storefronts.items():
        secrets = {key.lower(): value for key, value in _toml(
            Path(mounts["/etc/arkhai/storefront.secrets.toml"])).items()}
        configuration = {key.lower(): value for key, value in _toml(
            Path(mounts["/etc/arkhai/storefront.toml"])).items()}
        key = secrets.get("wallet", {}).get("private_key")
        if key:
            derived = _identity("eip191", key)["identifier"]
            assert configuration["wallet"]["address"].lower() == derived.lower(), name
        if secrets.get("settlement", {}).get("arkhai_payments", {}).get("api_key"):
            stated = configuration.get("settlement", {}).get("arkhai_payments", {})
            assert not {"api_key", "api_key_env", "development_auth"} & set(stated), name


def test_the_vm_lane_dispute_credential_names_the_pinned_authority() -> None:
    authority = _toml(DOUBLE_FIXTURES / "dispute-authority.toml")
    (credential,) = _toml(IDENTITIES / "bob.storefront.secrets.toml")["DisputeCredential"]
    identity = ("interface", "origin", "account", "record_key")
    assert {key: credential[key] for key in identity} == {key: authority[key] for key in identity}
    assert credential["api_key"]
    assert "api_key_env" not in credential


# Each lane's payment storefront, the configuration its overlay mounts, and its
# settlement table's key.
_LANE_STOREFRONTS = {
    "vm": ("bob-storefront", "Settlement"),
    "apicredits": ("credits-storefront", "settlement"),
    "bare-metal": ("bare-metal-storefront", "Settlement"),
}


@pytest.mark.parametrize("stack", sorted(_LANE_STOREFRONTS))
def test_each_lane_ca_bundle_path_is_where_its_overlay_binds_the_lane_ca(stack: str) -> None:
    name, settlement = _LANE_STOREFRONTS[stack]
    mounts = _mounts(_render(stack)[name])
    configuration = _toml(Path(mounts["/etc/arkhai/storefront.toml"]))
    payments = configuration[settlement]["arkhai_payments"]
    assert mounts.get(payments["ca_bundle_path"]) == str(LANE_CA), (name, payments["ca_bundle_path"])
    assert "api_key_env" not in payments
    assert "api_key" not in payments


# --- overlay binds -------------------------------------------------------------


@pytest.mark.parametrize("overlay", OVERLAYS)
def test_every_overlay_bind_names_a_committed_file(overlay: str) -> None:
    """Each overlay states its binds literally, relative to the repository root;
    every source but a buyer's runtime directory exists in the checkout."""
    services = yaml.safe_load((REPO_ROOT / overlay).read_text(encoding="utf-8"))["services"]
    for name, service in services.items():
        sources = [entry.split(":", 1)[0] for entry in service.get("volumes", [])]
        sources += list(service.get("env_file", []))
        for source in sources:
            assert "$" not in source, (overlay, name, source)
            if not source.startswith(("./", "core/")):
                continue  # a named volume
            if source.startswith(RUNTIME_DIRECTORY):
                continue
            assert (REPO_ROOT / source).exists(), (overlay, name, source)
