"""The operator target validates domain, mode and capacity before any mutation."""
from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from e2e_harness import settings as settings_module
from e2e_harness.real_provisioning_target import (
    PROFILE, PROFILE_FILE, SECTION, BareMetalHost, RealProvisioningTarget,
    TargetInvalid, TargetNotConfigured, VmHost, load_real_provisioning_target,
)

CONFIG = Path(__file__).resolve().parents[2] / "config"
EXAMPLE = CONFIG / f"{PROFILE_FILE}.example"


def _example() -> dict[str, Any]:
    return yaml.safe_load(EXAMPLE.read_text())[SECTION]


def _with(change) -> dict[str, Any]:
    section = copy.deepcopy(_example())
    change(section)
    return {SECTION: section}


def _settings_from(directory: Path, profiles: str):
    for name in ("config.yml", "config-local.yml"):
        shutil.copy(CONFIG / name, directory / name)
    return settings_module._load_bootstrap(
        {"CONFIG_DIRECTORY": str(directory), "ACTIVE_PROFILES": profiles}
    ).settings


def test_example_loads_through_profile_and_selects_each_domain(tmp_path):
    shutil.copy(EXAMPLE, tmp_path / PROFILE_FILE)
    settings = _settings_from(tmp_path, f"local,{PROFILE}")
    assert settings.SELLER.API_URL == "http://localhost:8001"
    target = load_real_provisioning_target(settings)
    assert isinstance(target, RealProvisioningTarget)
    assert target.version == 2
    vm, bare_metal = target.host_for("vm"), target.host_for("bare_metal")
    assert isinstance(vm, VmHost) and isinstance(bare_metal, BareMetalHost)
    assert vm.host_id == "example-kvm-1" and vm.connection.ssh_port == 6001
    assert vm.access.mode == "direct" and vm.access.public_host == "192.0.2.10"
    assert bare_metal.access.mode == "relay" and bare_metal.physical_host_id == "example-machine-1"


def test_without_selected_profile_target_is_absent(tmp_path):
    shutil.copy(EXAMPLE, tmp_path / PROFILE_FILE)
    assert isinstance(load_real_provisioning_target(_settings_from(tmp_path, "local")), TargetNotConfigured)


def test_selected_profile_without_file_is_absent(tmp_path):
    result = load_real_provisioning_target(_settings_from(tmp_path, f"local,{PROFILE}"))
    assert isinstance(result, TargetNotConfigured)
    assert PROFILE in result.reason and PROFILE_FILE in result.reason


def test_only_one_domain_is_valid_and_other_lane_has_no_host():
    target = load_real_provisioning_target(_with(lambda s: s["hosts"].pop()))
    assert isinstance(target.host_for("vm"), VmHost)
    assert target.host_for("bare_metal") is None


@pytest.mark.parametrize("field", ["pool_id", "resource_id"])
@pytest.mark.parametrize("value", ["", 7, True])
def test_bare_metal_registration_identifier_is_nonempty_text(field, value):
    with pytest.raises(TargetInvalid, match=field):
        load_real_provisioning_target(_with(lambda s: s["hosts"][1].update({field: value})))


@pytest.mark.parametrize("value", ["", 7, True])
def test_vm_resource_identifier_is_nonempty_text(value):
    with pytest.raises(TargetInvalid, match="resource_id"):
        load_real_provisioning_target(_with(lambda s: s["hosts"][0].update(resource_id=value)))


@pytest.mark.parametrize("section", [None, [], "target"])
def test_nonmapping_is_invalid_not_missing(section):
    with pytest.raises(TargetInvalid, match=f"{SECTION} is .*not a mapping"):
        load_real_provisioning_target({SECTION: section})


@pytest.mark.parametrize("version", [0, 3, "2", True, 2.0, None])
def test_unknown_or_nonstrict_version_is_refused(version):
    with pytest.raises(TargetInvalid, match=f"{SECTION}.version is"):
        load_real_provisioning_target(_with(lambda s: s.update(version=version)))


@pytest.mark.parametrize("settings", [{"REAL_VM_TARGET": {"version": 1}}, {SECTION: {"version": 1}}])
def test_version_one_names_conversion_and_profile(settings):
    with pytest.raises(TargetInvalid) as error:
        load_real_provisioning_target(settings)
    text = str(error.value)
    assert "version 1" in text and PROFILE in text
    for field in ("hosts", "connection", "public_host", "listing_shape", "capacity"):
        assert field in text


@pytest.mark.parametrize(("change", "field"), [
    (lambda s: s["hosts"][0]["connection"].pop("ssh_user"), "connection.ssh_user"),
    (lambda s: s["hosts"][0]["connection"].update(ssh_usr="invented"), "connection.ssh_usr"),
    (lambda s: s["hosts"][0].update(physical_host_id="invented"), "physical_host_id"),
    (lambda s: s["hosts"][0].update(ssh_host_public_key="invented"), "ssh_host_public_key"),
    (lambda s: s["hosts"][1].update(listing_shape={"vcpu_count": 1, "ram_gb": 1, "disk_gb": 1}), "listing_shape"),
    (lambda s: s["hosts"][1].pop("physical_host_id"), "physical_host_id"),
    (lambda s: s["hosts"][1].pop("ssh_host_public_key"), "ssh_host_public_key"),
    (lambda s: s["hosts"][0]["access"].update(relay_id="invented"), "relay_id"),
    (lambda s: s["hosts"][1]["access"].update(public_host="192.0.2.1"), "public_host"),
    (lambda s: s["hosts"][0].pop("domain"), "domain"),
    (lambda s: s["hosts"][0].update(domain="unknown"), "domain"),
    (lambda s: s["hosts"][0]["access"].update(mode="unknown"), "mode"),
    (lambda s: s["hosts"][0]["connection"].update(private_key="invented"), "private_key"),
    (lambda s: s["hosts"][0]["access"].update(token="invented"), "token"),
    (lambda s: s.update(host={}), "host"),
    (lambda s: s.update(hosts=[]), "hosts"),
])
def test_missing_foreign_or_unknown_field_is_named(change, field):
    with pytest.raises(TargetInvalid) as error:
        load_real_provisioning_target(_with(change))
    assert field in str(error.value)


@pytest.mark.parametrize("index", [0, 1])
def test_two_hosts_of_same_domain_are_refused(index):
    with pytest.raises(TargetInvalid, match="hosts.domain.*repeated"):
        load_real_provisioning_target(_with(lambda s: s["hosts"].append(copy.deepcopy(s["hosts"][index]))))


@pytest.mark.parametrize("dimension", ["vcpu_count", "ram_gb", "disk_gb"])
def test_shape_exceeding_half_capacity_names_dimension(dimension):
    with pytest.raises(TargetInvalid, match=f"listing_shape.{dimension}.*fit twice"):
        load_real_provisioning_target(_with(lambda s: s["hosts"][0]["listing_shape"].update({dimension: s["hosts"][0]["capacity"][dimension]})))


@pytest.mark.parametrize("dimension", ["vcpu_count", "ram_gb", "disk_gb"])
@pytest.mark.parametrize("value", [0, -1, "2", True, 1.5])
@pytest.mark.parametrize("field", ["capacity", "listing_shape"])
def test_dimensions_require_positive_strict_integers(dimension, value, field):
    with pytest.raises(TargetInvalid) as error:
        load_real_provisioning_target(_with(lambda s: s["hosts"][0][field].update({dimension: value})))
    assert f"{field}.{dimension}" in str(error.value)


def test_optional_inputs_are_absent_by_default():
    target = load_real_provisioning_target({SECTION: _example()})
    assert target.host_for("vm").management_unit is None
    assert target.host_for("bare_metal").access.admission_log is None


def test_the_examples_commented_optional_inputs_are_valid_once_uncommented():
    text = EXAMPLE.read_text()
    for field in ("management_unit", "admission_log"):
        assert f"# {field}: " in text
        text = text.replace(f"# {field}: ", f"{field}: ")
    target = load_real_provisioning_target(yaml.safe_load(text))
    assert target.host_for("vm").management_unit
    assert target.host_for("bare_metal").access.admission_log


def test_management_unit_and_admission_log_are_accepted():
    def change(section):
        section["hosts"][0]["management_unit"] = "operator-agent@by\\x2dlabel.service"
        section["hosts"][1]["access"]["admission_log"] = "/var/lib/example/frps-admission.log"

    target = load_real_provisioning_target(_with(change))
    assert target.host_for("vm").management_unit == "operator-agent@by\\x2dlabel.service"
    assert target.host_for("bare_metal").access.admission_log == "/var/lib/example/frps-admission.log"


@pytest.mark.parametrize("unit", ["agent", "agent.socket", "../agent.service", "an agent.service", ""])
def test_management_unit_that_is_not_a_service_name_is_refused_naming_it(unit):
    with pytest.raises(TargetInvalid) as error:
        load_real_provisioning_target(_with(lambda s: s["hosts"][0].update(management_unit=unit)))
    assert "hosts.0.vm.management_unit" in str(error.value)


def test_management_unit_is_a_vm_host_field_only():
    with pytest.raises(TargetInvalid) as error:
        load_real_provisioning_target(_with(lambda s: s["hosts"][1].update(management_unit="agent.service")))
    assert "management_unit" in str(error.value)


@pytest.mark.parametrize("path", ["frps-admission.log", "./frps.log", "/var/lib/../etc/frps.log", ""])
def test_relative_or_escaping_admission_log_is_refused_naming_it(path):
    with pytest.raises(TargetInvalid) as error:
        load_real_provisioning_target(_with(lambda s: s["hosts"][1]["access"].update(admission_log=path)))
    assert "hosts.1.bare_metal.access.relay.admission_log" in str(error.value)


def test_admission_log_is_a_relay_access_field_only():
    with pytest.raises(TargetInvalid) as error:
        load_real_provisioning_target(_with(lambda s: s["hosts"][0]["access"].update(admission_log="/var/log/frps.log")))
    assert "admission_log" in str(error.value)


GUEST_ISOLATION = {
    "operator": {"host": "127.0.0.1", "port": 16002, "user": "example-observer",
                 "key_path": "/run/secrets/example-observer-key"},
    "private_destinations": {"refused": "10.20.0.7", "listed": "172.16.4.8"},
}


def _with_guest_isolation(section: dict) -> dict[str, Any]:
    return _with(lambda s: s["hosts"][0].update(guest_isolation=section))


def test_the_guest_isolation_section_is_accepted_and_absent_by_default():
    assert load_real_provisioning_target({SECTION: _example()}).host_for("vm").guest_isolation is None
    isolation = load_real_provisioning_target(
        _with_guest_isolation(copy.deepcopy(GUEST_ISOLATION))).host_for("vm").guest_isolation
    assert (isolation.operator.host, isolation.operator.port) == ("127.0.0.1", 16002)
    assert isolation.operator.key_path == "/run/secrets/example-observer-key"
    assert (isolation.private_destinations.refused,
            isolation.private_destinations.listed) == ("10.20.0.7", "172.16.4.8")


def test_the_private_destinations_are_optional():
    section = {"operator": copy.deepcopy(GUEST_ISOLATION["operator"])}
    isolation = load_real_provisioning_target(_with_guest_isolation(section)).host_for("vm").guest_isolation
    assert isolation.private_destinations is None


@pytest.mark.parametrize(("change", "field"), [
    (lambda g: g.update(token="invented"), "guest_isolation.token"),
    (lambda g: g["operator"].update(password="invented"), "guest_isolation.operator.password"),
    (lambda g: g["private_destinations"].update(other="10.0.0.9"),
     "guest_isolation.private_destinations.other"),
    (lambda g: g["operator"].pop("user"), "guest_isolation.operator.user"),
    (lambda g: g["private_destinations"].pop("listed"), "guest_isolation.private_destinations.listed"),
    (lambda g: g["operator"].update(key_path="observer-key"), "guest_isolation.operator.key_path"),
    (lambda g: g["operator"].update(key_path="/run/../etc/key"), "guest_isolation.operator.key_path"),
])
def test_an_unknown_missing_or_misplaced_guest_isolation_field_is_named(change, field):
    section = copy.deepcopy(GUEST_ISOLATION)
    change(section)
    with pytest.raises(TargetInvalid) as error:
        load_real_provisioning_target(_with_guest_isolation(section))
    assert field in str(error.value)


@pytest.mark.parametrize("which", ["refused", "listed"])
@pytest.mark.parametrize("address", [
    "192.0.2.10", "198.51.100.7", "169.254.169.254", "192.168.122.300", "fd00::1", "10.0.0.0/8", "",
])
def test_a_destination_outside_the_guest_policys_private_ranges_is_refused_naming_it(which, address):
    section = copy.deepcopy(GUEST_ISOLATION)
    section["private_destinations"][which] = address
    with pytest.raises(TargetInvalid) as error:
        load_real_provisioning_target(_with_guest_isolation(section))
    assert f"guest_isolation.private_destinations.{which}" in str(error.value)


@pytest.mark.parametrize("address", ["192.168.122.1", "192.168.122.40"])
def test_a_destination_on_the_guests_own_network_is_refused_naming_it(address):
    section = copy.deepcopy(GUEST_ISOLATION)
    section["private_destinations"]["listed"] = address
    with pytest.raises(TargetInvalid) as error:
        load_real_provisioning_target(_with_guest_isolation(section))
    text = str(error.value)
    assert "guest_isolation.private_destinations.listed" in text and "guests' own network" in text


def test_equal_destinations_are_refused_naming_both():
    section = copy.deepcopy(GUEST_ISOLATION)
    section["private_destinations"]["listed"] = section["private_destinations"]["refused"]
    with pytest.raises(TargetInvalid) as error:
        load_real_provisioning_target(_with_guest_isolation(section))
    text = str(error.value)
    assert "guest_isolation.private_destinations" in text and "listed must differ from refused" in text


def test_guest_isolation_is_a_vm_host_field_only():
    with pytest.raises(TargetInvalid) as error:
        load_real_provisioning_target(
            _with(lambda s: s["hosts"][1].update(guest_isolation=copy.deepcopy(GUEST_ISOLATION))))
    assert "guest_isolation" in str(error.value)


def test_the_examples_commented_guest_isolation_section_is_valid_once_uncommented():
    lines = EXAMPLE.read_text().splitlines()
    start = lines.index("      # guest_isolation:")
    block = [start]
    while lines[block[-1] + 1].startswith("      #   "):
        block.append(block[-1] + 1)
    for index in block:
        lines[index] = lines[index].replace("# ", "", 1)
    isolation = load_real_provisioning_target(yaml.safe_load("\n".join(lines))).host_for("vm").guest_isolation
    assert isolation.operator.key_path.startswith("/run/secrets/example-")
    assert isolation.private_destinations is not None


def test_relay_vm_access_and_direct_bare_metal_access_are_both_valid():
    section = _example()
    section["hosts"][0]["access"] = {"mode": "relay", "relay_id": "example-vm-relay"}
    section["hosts"][1]["access"] = {"mode": "direct", "public_host": "192.0.2.1"}
    target = load_real_provisioning_target({SECTION: section})
    assert target.host_for("vm").access.relay_id == "example-vm-relay"
    assert target.host_for("bare_metal").access.public_host == "192.0.2.1"
