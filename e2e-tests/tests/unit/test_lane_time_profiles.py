"""Each lane's time: its profile section builds and restates its sources, and its
configuration injects every party.

The committed runner profiles (`config/config-<lane>-lane.yml`) name every party
of their lane; each is built over its typed client here, as the session fixture
builds it, with no network call. Every value a section restates — an
administrator credential or pin, a registry's administrator key, a double's
control token, the credits and inference operators — is held to the committed file it comes
from, so a wrong copy fails here rather than as a lane's setup. And every
service party is held to injected time by the lane's own configuration, read
in the form that party takes its settings in. Every value is a public
development fixture, never used on any network.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml
from market_identity import create_signer

from tests.e2e.roles.helpers.lane_time import parties_from

E2E = Path(__file__).resolve().parents[2]
REPO = E2E.parent
LANES = ("vms", "bare-metal", "apicredits", "inference")
#: Each lane's parties, by name and kind, as the lane runs them.
PARTIES = {
    "vms": [("bob-storefront", "storefront"), ("alice-storefront", "storefront"),
            ("bob-provisioning", "provisioning"), ("alice-provisioning", "provisioning"),
            ("registry-a", "registry"), ("registry-b", "registry"),
            ("payments-double", "control"), ("mediation-double", "control"),
            ("anvil", "chain"), ("buyer-file", "buyer")],
    "bare-metal": [("bare-metal-storefront", "storefront"),
                   ("bare-metal-provisioning", "provisioning"),
                   ("bare-metal-registry", "registry"),
                   ("payments-double", "control"), ("mediation-double", "control"),
                   ("anvil", "chain"), ("buyer-file", "buyer")],
    "apicredits": [("credits-storefront", "storefront"), ("credits-service", "credits"),
                   ("api-credits-registry", "registry"), ("compute-registry", "registry"),
                   ("payments-double", "control"), ("mediation-double", "control"),
                   ("sample-app", "control"), ("anvil", "chain"), ("buyer-file", "buyer")],
    "inference": [("inference-storefront", "storefront"), ("inference-service", "inference"),
                  ("inference-registry", "registry"), ("compute-registry", "registry"),
                  ("api-credits-registry", "registry"),
                  ("payments-double", "control"), ("mediation-double", "control"),
                  ("inference-gateway", "control"), ("anvil", "chain"), ("buyer-file", "buyer")],
}
#: Where each lane configures each service party's time source, in the form that
#: party takes its settings in: a storefront's lane configuration file, mounted
#: by the lane's overlay; a provisioning service's lane profile, and a
#: registry's, each layered through the service's ACTIVE_PROFILES; and the
#: environment of a service configured by it.
CONFIGURED = {
    "vms": {
        "bob-storefront": ("storefront", "compose.vms-lane.yml", "bob-storefront"),
        "alice-storefront": ("storefront", "compose.vms-lane.yml", "alice-storefront"),
        "bob-provisioning": ("provisioning", "compose.vms-lane.yml", "provisioning"),
        "alice-provisioning": ("provisioning", "compose.vms-lane.yml", "alice-provisioning"),
        "registry-a": ("registry", "compose.vms-lane.yml", "registry"),
        "registry-b": ("registry", "compose.vms-lane.yml", "registry-b"),
    },
    "bare-metal": {
        "bare-metal-storefront": ("storefront", "compose.bare-metal-local.yml",
                                  "bare-metal-storefront"),
        "bare-metal-provisioning": ("provisioning", "compose.bare-metal-local.yml",
                                    "bare-metal-provisioning"),
        "bare-metal-registry": ("registry", "compose.bare-metal-local.yml",
                                "bare-metal-registry"),
    },
    "apicredits": {
        "credits-storefront": ("storefront", "compose.apicredits-lane.yml", "credits-storefront"),
        "credits-service": ("environment", "compose.apicredits-lane.yml", "credits-service",
                            "APICREDITS_TIME__SOURCE"),
        "api-credits-registry": ("registry", "compose.apicredits-lane.yml",
                                 "api-credits-registry"),
        "compute-registry": ("registry", "compose.apicredits-lane.yml", "compute-registry"),
        "sample-app": ("environment", "compose.apicredits-lane.yml", "sample-app",
                       "APICREDITS_SAMPLE_APP_TIME_SOURCE"),
    },
    "inference": {
        "inference-storefront": ("storefront", "compose.inference-lane.yml",
                                 "inference-storefront"),
        "inference-service": ("environment", "compose.inference-lane.yml", "inference-service",
                              "INFERENCE_TIME__SOURCE"),
        "inference-registry": ("registry", "compose.inference-lane.yml", "inference-registry"),
        "compute-registry": ("registry", "compose.inference-lane.yml", "compute-registry"),
        "api-credits-registry": ("registry", "compose.inference-lane.yml",
                                 "api-credits-registry"),
        "inference-gateway": ("environment", "compose.inference-lane.yml", "inference-gateway",
                              "INFERENCE_GATEWAY_TIME_SOURCE"),
    },
}
#: The doubles, which every lane layers from one overlay.
DOUBLES = {
    "payments-double": ("environment", "compose.payments-double.yml", "payments-double",
                        "PAYMENTS_LANE_DOUBLE_TIME_SOURCE"),
    "mediation-double": ("environment", "compose.payments-double.yml", "mediation-double",
                         "MEDIATION_LANE_DOUBLE_TIME_SOURCE"),
}
#: The registry profile each lane registry reads its administrator key from.
REGISTRY_PROFILES = {
    "registry-a": "config-registry-a.env", "registry-b": "config-registry-b.env",
    "bare-metal-registry": "config-bare-metal-registry.env",
    "api-credits-registry": "config-api-credits-registry.env",
    "compute-registry": "config-compute-registry.env",
    "inference-registry": "config-inference-registry.env",
}


def _section(lane: str) -> dict[str, Any]:
    profile = yaml.safe_load((E2E / "config" / f"config-{lane}-lane.yml").read_text())
    return profile["lane_time"]


def _parties(lane: str) -> dict[str, dict[str, Any]]:
    return {entry["name"]: entry for entry in _section(lane)["parties"]}


def _docker() -> dict[str, Any]:
    return yaml.safe_load((E2E / "config" / "config-docker.yml").read_text())


def _env(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines()
                if line and not line.startswith("#") and "=" in line)


def _address(credential: str) -> str:
    return create_signer("eip191", credential).identity.identifier.lower()


@pytest.mark.parametrize("lane", LANES)
def test_every_party_of_the_lane_is_named_and_built_over_its_client(lane: str, tmp_path) -> None:
    section = _section(lane)
    entries = [dict(entry) for entry in section["parties"]]
    # The buyer's file and the lane CA's path are the runner's; built here under a
    # temporary root and from the committed CA the runner mounts there.
    for entry in entries:
        if entry["kind"] == "buyer":
            entry["file"] = str(tmp_path / "lane-time.json")
        if entry.get("ca_bundle_path"):
            assert entry["ca_bundle_path"] == "/run/lane-doubles/lane-ca.pem", entry["name"]
            entry["ca_bundle_path"] = str(REPO / "tools/lane-double-controls/tls/lane-ca.pem")

    parties = parties_from({"parties": entries})

    assert section["mode"] == "injected"
    assert [(party.name, party.kind) for party in parties] == PARTIES[lane]


def _service(compose: str, service: str) -> dict[str, Any]:
    return yaml.safe_load((REPO / compose).read_text())["services"][service]


def _environment(compose: str, service: str) -> dict[str, str]:
    return dict(entry.split("=", 1) for entry in _service(compose, service).get("environment", []))


def _source(form: str, compose: str, service: str, *variable: str) -> str | None:
    """The time source a lane's configuration gives one service, read the way
    that service takes its settings."""
    if form == "environment":
        return _environment(compose, service).get(variable[0])
    if form == "storefront":
        [mounted] = [volume.split(":")[0] for volume in _service(compose, service)["volumes"]
                     if volume.split(":")[1] == "/etc/arkhai/storefront.toml"]
        return tomllib.loads((REPO / mounted).read_text())["Time"]["source"]
    profiles = _environment(compose, service)["ACTIVE_PROFILES"].split(",")
    if form == "provisioning":
        assert "lane-time" in profiles, service
        lane = yaml.safe_load((REPO / "dev-env/provisioning/config-lane-time.yml").read_text())
        return lane["time"]["source"]
    assert "payments-lane" in profiles, service
    return _env(REPO / "dev-env/registry/config-payments-lane.env").get("TIME_SOURCE")


@pytest.mark.parametrize("lane", LANES)
def test_every_service_party_of_the_lane_is_configured_for_injected_time(lane: str) -> None:
    """`test-compatibility`'s "Every party in a lane shares one lane time": each
    party the profile names, but the chain and the buyer's file, which the
    harness sets, runs injected time by the lane's own configuration. Each
    overlay is read as committed, not rendered with the files under it."""
    services = {name for name, kind in PARTIES[lane] if kind not in {"chain", "buyer"}}
    configured = {**CONFIGURED[lane], **DOUBLES}

    assert services == set(configured)
    for name, where in configured.items():
        assert _source(*where) == "injected", name


def test_alice_s_lane_configuration_is_her_full_stack_one_with_the_lane_s_time() -> None:
    lane = tomllib.loads((REPO / "domains/vms/storefront/storefront.alice.lane.toml").read_text())
    full = tomllib.loads((REPO / "domains/vms/storefront/storefront.alice.toml").read_text())

    assert lane.pop("Time") == {"source": "injected"}
    assert lane == full


def test_the_inference_lane_configuration_is_its_full_stack_one_with_the_lane_s_time() -> None:
    storefront = REPO / "domains/inference/storefront"
    lane = tomllib.loads((storefront / "storefront.inference.lane.toml").read_text())
    full = tomllib.loads((storefront / "storefront.inference.toml").read_text())

    assert lane.pop("Time") == {"source": "injected"}
    assert lane == full


def test_the_inference_stack_s_own_files_choose_no_time_source() -> None:
    """The full local stack layers the inference domain's topology and its
    development overlay, never the lane's: there the service, the gateway and
    the storefront keep their default, wall time, and the gateway is given no
    control token, so it serves no time control."""
    for compose in ("domains/inference/compose.yml", "compose.inference-local.yml"):
        for name, service in yaml.safe_load((REPO / compose).read_text())["services"].items():
            environment = service.get("environment") or []
            # The buyer service states its environment as a mapping.
            names = environment if isinstance(environment, dict) else [
                entry.split("=", 1)[0] for entry in environment]
            assert not [entry for entry in names
                        if entry.endswith(("TIME_SOURCE", "TIME__SOURCE", "CONTROL_TOKEN"))], name
    full = tomllib.loads(
        (REPO / "domains/inference/storefront/storefront.inference.toml").read_text())
    assert "Time" not in full


def test_the_inference_gateway_s_control_token_is_the_one_the_lane_gives_it() -> None:
    environment = _environment("compose.inference-lane.yml", "inference-gateway")

    assert _parties("inference")["inference-gateway"]["token"] == (
        environment["INFERENCE_GATEWAY_CONTROL_TOKEN"])


def test_the_sample_app_s_control_token_is_the_one_the_lane_gives_it() -> None:
    environment = _environment("compose.apicredits-lane.yml", "sample-app")

    assert _parties("apicredits")["sample-app"]["token"] == (
        environment["APICREDITS_SAMPLE_APP_CONTROL_TOKEN"])


@pytest.mark.parametrize("lane", LANES)
def test_each_registry_s_administrator_key_is_its_profile_s(lane: str) -> None:
    for name, entry in _parties(lane).items():
        if entry["kind"] == "registry":
            profile = _env(REPO / "dev-env" / "registry" / REGISTRY_PROFILES[name])
            assert entry["admin_key"] == profile["REGISTRY_ADMIN_API_KEY"], name
            assert entry["authority_id"] == profile["REGISTRY_AUTHORITY_ID"], name
            assert entry["authority_identifier"] == profile["REGISTRY_AUTHORITY_IDENTIFIER"], name


@pytest.mark.parametrize("lane", LANES)
def test_each_double_s_control_token_is_its_fixture_s(lane: str) -> None:
    tokens = {
        "payments-double": tomllib.loads(
            (REPO / "tools/payments-lane-double/fixtures/accounts.toml").read_text()),
        "mediation-double": tomllib.loads(
            (REPO / "tools/mediation-lane-double/fixtures/authority.toml").read_text()),
    }
    parties = _parties(lane)

    for name, fixture in tokens.items():
        assert parties[name]["token"] == fixture["control_token"], name


def test_the_service_credentials_are_the_runner_s_own() -> None:
    docker = _docker()
    vms, bare_metal, credits = _parties("vms"), _parties("bare-metal"), _parties("apicredits")
    inference = _parties("inference")

    assert vms["bob-storefront"]["admin_credential"] == docker["seller"]["admin_credential"]
    assert vms["bob-storefront"]["publisher_identifier"] == docker["seller"]["wallet_address"].lower()
    assert vms["alice-storefront"]["admin_credential"] == docker["alice"]["admin_credential"]
    assert vms["alice-storefront"]["publisher_identifier"] == docker["alice"]["wallet_address"].lower()
    for name, section in (("bob-provisioning", "provisioning"),
                          ("alice-provisioning", "alice_provisioning")):
        assert vms[name]["admin_credential"] == docker[section]["admin_credential"], name
        assert vms[name]["authority_identifier"] == docker[section]["authority_identifier"], name
    lane = docker["bare_metal_lane"]
    assert bare_metal["bare-metal-storefront"]["admin_credential"] == lane["storefront_admin_credential"]
    assert bare_metal["bare-metal-storefront"]["publisher_identifier"] == lane["storefront_identifier"]
    assert bare_metal["bare-metal-provisioning"]["admin_credential"] == lane["site_admin_credential"]
    assert bare_metal["bare-metal-provisioning"]["authority_identifier"] == (
        lane["site_authority_identifier"])
    api = docker["api_credits"]
    assert credits["credits-storefront"]["admin_credential"] == api["storefront_admin_credential"]
    assert credits["credits-storefront"]["publisher_identifier"] == api["storefront_identifier"]
    # The inference storefront's administrator is its seller principal.
    seller = docker["inference"]["seller_marketplace_credential"]
    assert inference["inference-storefront"]["admin_credential"] == seller
    assert inference["inference-storefront"]["publisher_identifier"] == _address(seller)
    assert inference["inference-service"]["authority_identifier"] == (
        docker["inference"]["service_authority_identifier"])


def test_the_credits_operator_is_the_principal_the_lane_trusts_as_admin() -> None:
    compose = yaml.safe_load((REPO / "compose.apicredits-lane.yml").read_text())
    [setting] = [entry for entry in compose["services"]["credits-service"]["environment"]
                 if entry.startswith("APICREDITS_TRUSTED_PRINCIPALS=")]
    principals = json.loads(re.sub(r"^APICREDITS_TRUSTED_PRINCIPALS=@json ", "", setting))
    sample_app = yaml.safe_load((REPO / "domains/apicredits/compose.yml").read_text())
    [authority] = [entry for entry in sample_app["services"]["sample-app"]["environment"]
                   if entry.startswith("APICREDITS_MIDDLEWARE_AUTHORITY_PRINCIPALS=")]
    operator = _parties("apicredits")["credits-service"]

    assert principals["admin"] == [{"scheme": operator["admin_scheme"],
                                    "identifier": _address(operator["admin_credential"])}]
    assert json.loads(authority.split("=", 1)[1]) == [
        {"scheme": operator["authority_scheme"], "identifier": operator["authority_identifier"]}]


def test_the_inference_operator_is_the_principal_the_lane_trusts_as_admin() -> None:
    def principals(compose: str) -> dict[str, Any]:
        [setting] = [entry for entry in _service(compose, "inference-service")["environment"]
                     if entry.startswith("INFERENCE_TRUSTED_PRINCIPALS=")]
        return json.loads(re.sub(r"^INFERENCE_TRUSTED_PRINCIPALS=@json ", "", setting))

    lane, stack = principals("compose.inference-lane.yml"), principals("domains/inference/compose.yml")
    [authority] = [entry for entry in
                   _service("domains/inference/compose.yml", "inference-gateway")["environment"]
                   if entry.startswith("INFERENCE_GATEWAY_AUTHORITY_PRINCIPALS=")]
    operator = _parties("inference")["inference-service"]

    assert lane.pop("admin") == [{"scheme": operator["admin_scheme"],
                                  "identifier": _address(operator["admin_credential"])}]
    # The lane adds the operator to the stack's principals and changes no other.
    assert lane == stack
    assert json.loads(authority.split("=", 1)[1]) == [
        {"scheme": operator["authority_scheme"], "identifier": operator["authority_identifier"]}]
