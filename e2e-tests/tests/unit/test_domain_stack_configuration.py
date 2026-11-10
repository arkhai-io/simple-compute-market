"""Static stack contracts that protect role and package boundaries."""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path

import pytest
import yaml

from e2e_harness import settings as settings_module

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DOUBLE = _REPO_ROOT / "tools/payments-lane-double"
_PAYMENTS = "arkhai.payments.v1"
_CA_MOUNT = "/run/lane-doubles/lane-ca.pem"


def _toml(relative: str | Path) -> dict:
    return tomllib.loads((_REPO_ROOT / relative).read_text(encoding="utf-8"))


def _compose(relative: str) -> dict:
    return yaml.safe_load((_REPO_ROOT / relative).read_text(encoding="utf-8"))


def test_api_credit_stack_has_no_committed_admin_credential():
    """The domain file names the admin key's container path and binds nothing;
    the development overlay binds the committed development key there for each
    service that reads it."""
    compose = (_REPO_ROOT / "domains/apicredits/compose.yml").read_text(
        encoding="utf-8"
    )
    storefront = (
        _REPO_ROOT / "domains/apicredits/storefront/storefront.credits.toml"
    ).read_text(encoding="utf-8")
    overlay = _compose("compose.apicredits-local.yml")["services"]

    assert "test-api-key" not in compose + storefront
    assert "api-credits-admin-key:ro" not in compose
    binding = "./dev-env/identities/api-credits-admin-key:/run/secrets/arkhai/api-credits-admin-key:ro"
    assert [name for name, service in overlay.items() if binding in service.get("volumes", [])] == [
        "credits-service", "sample-app", "credits-storefront",
    ]
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

    The version is not written in the image definition at all: the install
    step reads it from the project's pyproject and refuses any package index,
    so the image cannot install a release other than the one the tree builds.
    """

    dockerfile = (_REPO_ROOT / "domains/apicredits/storefront/Dockerfile").read_text(
        encoding="utf-8"
    )

    assert (
        "uv_project.py install-wheel --project /repo/domains/apicredits/storefront"
        in dockerfile
    )
    assert "arkhai-apicredits-storefront==" not in dockerfile
    assert "COPY domains/apicredits/storefront/src" not in dockerfile
    assert 'ENV PYTHONPATH="/app"' not in dockerfile


def test_bare_metal_stack_requires_real_selected_site_inputs():
    domain_compose = (_REPO_ROOT / "domains/bare_metal/compose.yml").read_text(
        encoding="utf-8"
    )
    wrapper = (_REPO_ROOT / "compose.bare-metal.yml").read_text(encoding="utf-8")
    rendered = domain_compose + wrapper

    assert "arkhai:bare-metal-storefront" in domain_compose
    # Real provisioning; only the lane's overlay appends the run's mode.
    assert "ACTIVE_PROFILES=docker\n" in domain_compose
    provisioning = yaml.safe_load(domain_compose)["services"]["bare-metal-provisioning"]
    assert not [item for item in provisioning["environment"] if "mock" in item]
    assert "MOCK_PROVISIONING" not in rendered
    # The definition documents' container paths are topology; the documents
    # themselves, and the storefront's configuration, are the deployment's, with
    # no committed fallback.
    assert "PROVISIONING_HOST_DEFINITIONS_PATH=/run/config/host-definitions.yaml" in domain_compose
    assert "PROVISIONING_POOL_DEFINITIONS_PATH=/run/config/resource-pools.yaml" in domain_compose
    services = {
        **yaml.safe_load(domain_compose)["services"], **yaml.safe_load(wrapper)["services"],
    }
    for name, service in services.items():
        binds = [str(entry) for entry in service.get("volumes", [])]
        binds += list(service.get("env_file", []))
        assert not [
            bind for bind in binds
            if "dev-env" in bind or bind.endswith(":/etc/arkhai/storefront.toml:ro")
        ], name
    # The service refuses either retired inventory setting at startup.
    assert "INVENTORY" not in rendered


def test_bare_metal_lane_delivers_seller_mail_to_its_mail_sink():
    """The lane's storefront mails each revealed buyer contact to a Mailpit the
    lane runs, at the host its delivery configuration names, which the
    introduction scenarios read back through ``MAILPIT.API_URL``."""
    overlay = yaml.safe_load(
        (_REPO_ROOT / "compose.bare-metal-local.yml").read_text(encoding="utf-8")
    )
    storefront = tomllib.loads(
        (_REPO_ROOT / "domains/bare_metal/storefront/storefront.dev.toml").read_text(
            encoding="utf-8"
        )
    )
    settings = yaml.safe_load(
        (_REPO_ROOT / "e2e-tests/config/config-docker.yml").read_text(encoding="utf-8")
    )

    services = overlay["services"]
    assert services["mailpit"]["image"].startswith("docker.io/axllent/mailpit:")
    assert services["bare-metal-storefront"]["depends_on"]["mailpit"] == {
        "condition": "service_healthy"
    }
    delivery = storefront["Delivery"]
    assert delivery["enabled"] == ["seller-mail"]
    mail = delivery["seller-mail"]
    assert (mail["sink"], mail["host"], mail["port"]) == ("smtp", "mailpit", 1025)
    # The seller is mailed at the contact the storefront reveals for its site.
    assert mail["recipients"] == [
        storefront["Settlement"]["contact"]["contact_payload"]["email"]
    ]
    assert mail["recipients"] == [settings["bare_metal_lane"]["seller_contact_email"]]
    assert settings["mailpit"]["api_url"] == "http://mailpit:8025"


def test_bare_metal_stack_keeps_role_credentials_and_state_separate():
    domain_compose = (_REPO_ROOT / "domains/bare_metal/compose.yml").read_text(
        encoding="utf-8"
    )
    wrapper = (_REPO_ROOT / "compose.bare-metal.yml").read_text(encoding="utf-8")
    overlay = _compose("compose.bare-metal-local.yml")["services"]

    assert "ARKHAI_IDENTITY_CREDENTIAL=" not in wrapper
    assert "private_key" not in wrapper.lower()
    # Each role's credential is its own file, bound by the lane's overlay; the
    # seller wallet's key arrives in the storefront's secret overlay file, never
    # inline.
    assert (
        "./dev-env/identities/registry-a.eip191:/run/secrets/arkhai/registry-identity/credential:ro"
        in overlay["bare-metal-registry"]["volumes"]
    )
    assert overlay["bare-metal-provisioning"]["env_file"] == [
        "./dev-env/identities/provisioning.identity.env"
    ]
    assert overlay["bare-metal-storefront"]["env_file"] == ["./dev-env/identities/bob.identity.env"]
    assert (
        "./dev-env/identities/bare-metal.storefront.secrets.toml:/etc/arkhai/storefront.secrets.toml:ro"
        in overlay["bare-metal-storefront"]["volumes"]
    )
    for name in (
        "bare-metal-registry-data",
        "bare-metal-redis-data",
        "bare-metal-provisioning-data",
        "bare-metal-storefront-data",
    ):
        assert f"{name}:" in domain_compose


# --- the payments lane double in the lanes -------------------------------------
#
# Each lane's payment storefront settles against the lane's payments double. The
# double's committed fixtures (tools/payments-lane-double/fixtures) are the one
# source of the receipt identity and the accounts; a storefront configuration is
# a static file, so these checks hold its copies to the fixtures. Every value is
# a public development value.

# (lane configuration, its settlement table's key, the overlay that wires the
# lane's storefront and that storefront's service, the stack profile it extends)
_LANE_STOREFRONTS = (
    ("domains/vms/storefront/storefront.bob.lane.toml", "Settlement",
     "compose.vms-lane.yml", "bob-storefront", "domains/vms/storefront/storefront.bob.toml"),
    ("domains/bare_metal/storefront/storefront.dev.toml", "Settlement",
     "compose.bare-metal-local.yml", "bare-metal-storefront", None),
    ("domains/apicredits/storefront/storefront.credits.lane.toml", "settlement",
     "compose.apicredits-lane.yml", "credits-storefront",
     "domains/apicredits/storefront/storefront.credits.toml"),
)
# Every registry a lane's storefronts publish to or its buyers discover through,
# and the overlay that sets its lane profiles.
_LANE_REGISTRIES = (
    ("compose.vms-lane.yml", "registry"),
    ("compose.vms-lane.yml", "registry-b"),
    ("compose.bare-metal-local.yml", "bare-metal-registry"),
    ("compose.apicredits-lane.yml", "api-credits-registry"),
    ("compose.apicredits-lane.yml", "compute-registry"),
)
# Variables a storefront would read its payments trust or key from; the lanes
# configure both instead.
_PAYMENTS_VARIABLES = {"SSL_CERT_FILE", "ARKHAI_PAYMENTS_API_KEY"}


def _environment(service: dict) -> dict[str, str]:
    return dict(item.split("=", 1) for item in service.get("environment", []))


def _without_lane_payments(config: dict, settlement: str) -> dict:
    """``config`` without what a lane adds for payments."""
    stripped = copy.deepcopy(config)
    table = stripped[settlement]
    table.pop("arkhai_payments", None)
    table["priority"] = [item for item in table["priority"] if item != _PAYMENTS]
    stripped.pop("DisputeCredential", None)
    pricing = stripped.get("pricing", {})
    pricing["settlements"] = [
        clause for clause in pricing.get("settlements", []) if clause["mechanism"] != _PAYMENTS
    ]
    if not pricing["settlements"]:
        del pricing["settlements"]
    return stripped


@pytest.mark.parametrize(
    ("lane", "settlement", "profile"),
    [(lane, settlement, profile) for lane, settlement, _, _, profile in _LANE_STOREFRONTS if profile],
)
def test_a_lane_storefront_configuration_is_its_stack_profile_plus_payments(
    lane, settlement, profile
):
    """The VM and API-credit lanes run their own copy of a profile the full local
    stack also runs, so the stack runs no payments; the copy differs only in
    what payments adds."""
    assert _without_lane_payments(_toml(lane), settlement) == _without_lane_payments(
        _toml(profile), settlement
    )
    assert not (_toml(profile)[settlement].get("arkhai_payments") or {}).get("enabled")


@pytest.mark.parametrize(("lane", "settlement"), [item[:2] for item in _LANE_STOREFRONTS])
def test_each_lane_storefront_settles_against_the_double(lane, settlement):
    accounts = _toml(_DOUBLE / "fixtures/accounts.toml")
    config = _toml(lane)
    payments = config[settlement]["arkhai_payments"]

    assert _PAYMENTS in config[settlement]["priority"]
    # The key is in the storefront's secret overlay, never named here.
    assert payments == {
        "enabled": True,
        "service_url": "https://payments-double:8443",
        "service_identity": accounts["receipt_identity"],
        "fee_bps": accounts["fee_bps"],
        "livemode": False,
        "ca_bundle_path": _CA_MOUNT,
    }
    # The dispute authority reaches the seller through its registries alone.
    assert "dispute" not in {key.lower() for key in config}


@pytest.mark.parametrize(("lane", "overlay", "service"), [
    (item[0], *item[2:4]) for item in _LANE_STOREFRONTS
])
def test_each_lane_overlay_wires_its_storefront_to_the_double(lane, overlay, service):
    storefront = _compose(overlay)["services"][service]

    assert storefront["depends_on"]["payments-double"] == {"condition": "service_healthy"}
    assert not set(_environment(storefront)) & _PAYMENTS_VARIABLES
    assert f"./tools/lane-double-controls/tls/lane-ca.pem:{_CA_MOUNT}:ro" in storefront["volumes"]
    assert f"./{lane}:/etc/arkhai/storefront.toml:ro" in storefront["volumes"]


@pytest.mark.parametrize(("overlay", "service"), _LANE_REGISTRIES)
def test_each_lane_registry_layers_the_lane_profile(overlay, service):
    environment = _environment(_compose(overlay)["services"][service])

    assert environment["ACTIVE_PROFILES"].split(",")[-1] == "payments-lane"
    assert not {key for key in environment if key.startswith("REGISTRY_")}


def test_the_api_credit_lane_listing_pays_the_double_seller_account():
    accounts = _toml(_DOUBLE / "fixtures/accounts.toml")
    pricing = _toml("domains/apicredits/storefront/storefront.credits.lane.toml")["pricing"]
    (clause,) = [item for item in pricing["settlements"] if item["mechanism"] == _PAYMENTS]

    assert clause["asset"] == clause["mechanism_input"]["asset"] == accounts["asset"]
    assert clause["mechanism_input"]["payee_account"] == accounts["accounts"]["seller"]["account"]


# Each lane's runner profile, the identity file its storefront signs with, and
# what only that lane's payment scenario reads.
_RUNNER_LANES = {
    "vms-lane": ("bob.identity.env", set()),
    "apicredits-lane": ("api-credits.identity.env", set()),
    "bare-metal-lane": ("bob.identity.env", {"COMPUTE_HOURLY_GROSS", "DISPUTE_WINDOW"}),
}


def _runner_payments(profiles: str) -> dict:
    """The runner's PAYMENTS section as its own loader resolves `profiles` from
    the committed config directory."""
    loaded = settings_module._load_bootstrap({
        "CONFIG_DIRECTORY": str(_REPO_ROOT / "e2e-tests/config"), "ACTIVE_PROFILES": profiles,
    }).settings
    return {str(key).upper(): value for key, value in loaded.get("PAYMENTS", {}).items()}


@pytest.mark.parametrize("lane", sorted(_RUNNER_LANES))
def test_a_lane_runner_loads_a_complete_payments_section(lane):
    """The shared profile and the lane's merge key by key over the defaults into
    every setting the payment scenarios require, with the lane's own seller."""
    identity, extras = _RUNNER_LANES[lane]
    payments = _runner_payments(f"docker,payments-lane,{lane}")
    required = {
        "SERVICE_URL", "SERVICE_IDENTITY", "BUYER_ACCOUNT", "SELLER_ACCOUNT",
        "BUYER_MARKETPLACE_CREDENTIAL", "SELLER_MARKETPLACE_CREDENTIAL", "API_KEY_ENV",
        "BUYER_API_KEY", "CA_BUNDLE_PATH", *extras,
    }
    assert all(payments.get(key) not in (None, "") for key in required), payments
    assert payments["LANE_OWNED"] is True and payments["LIVEMODE"] is False
    credential = dict(
        line.split("=", 1)
        for line in (_REPO_ROOT / "dev-env/identities" / identity).read_text().splitlines()
        if line and not line.startswith("#")
    )["ARKHAI_IDENTITY_CREDENTIAL"]
    assert payments["SELLER_MARKETPLACE_CREDENTIAL"] == credential


def test_a_runner_without_the_lane_profiles_has_no_payments_target():
    payments = _runner_payments("docker")
    assert not payments.get("SERVICE_URL")
    assert not payments.get("BUYER_API_KEY")
    assert not payments.get("LANE_OWNED")


def test_the_double_runs_only_in_the_lanes_and_publishes_no_host_port():
    double = _compose("compose.payments-double.yml")["services"]["payments-double"]
    makefile = (_REPO_ROOT / "e2e-tests/Makefile").read_text(encoding="utf-8")
    full_stack = (_REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert double["image"] == "arkhai:payments-lane-double"
    assert "ports" not in double
    assert makefile.count("-f compose.payments-double.yml") == 3
    assert "payments" not in full_stack
    for shared in ("compose.vms-local.yml", "compose.apicredits-local.yml"):
        services = _compose(shared)["services"]
        assert "payments-double" not in services
        for name, service in services.items():
            environment = service.get("environment") or []
            assert not [item for item in environment if "payments-lane" in str(item)], name
            assert not set(_environment(service) if isinstance(environment, list) else environment) & (
                _PAYMENTS_VARIABLES
            ), name
