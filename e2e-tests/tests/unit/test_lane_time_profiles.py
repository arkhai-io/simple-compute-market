"""Each lane profile's lane_time section builds, and restates its sources exactly.

The committed runner profiles (`config/config-<lane>-lane.yml`) name every party
of their lane; each is built over its typed client here, as the session fixture
builds it, with no network call. Every value a section restates — an
administrator credential or pin, a registry's administrator key, a double's
control token, the credits operator — is held to the committed file it comes
from, so a wrong copy fails here rather than as a lane's setup. Every value is a
public development fixture, never used on any network.
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
LANES = ("vms", "bare-metal", "apicredits")
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
                   ("anvil", "chain"), ("buyer-file", "buyer")],
}
#: The registry profile each lane registry reads its administrator key from.
REGISTRY_PROFILES = {
    "registry-a": "config-registry-a.env", "registry-b": "config-registry-b.env",
    "bare-metal-registry": "config-bare-metal-registry.env",
    "api-credits-registry": "config-api-credits-registry.env",
    "compute-registry": "config-compute-registry.env",
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

    assert section["mode"] in {"injected", "wall"}
    assert [(party.name, party.kind) for party in parties] == PARTIES[lane]


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
