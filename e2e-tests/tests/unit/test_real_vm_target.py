"""The real-provisioning target is read, validated, and refused as its format says."""

from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from e2e_harness import settings as settings_module
from e2e_harness.real_vm_target import (
    PROFILE,
    PROFILE_FILE,
    SECTION,
    RealVmTarget,
    TargetInvalid,
    TargetNotConfigured,
    load_real_vm_target,
)

CONFIG = Path(__file__).resolve().parents[2] / "config"
EXAMPLE = CONFIG / f"{PROFILE_FILE}.example"


def _example() -> dict[str, Any]:
    return yaml.safe_load(EXAMPLE.read_text())[SECTION]


def _with(change) -> dict[str, Any]:
    section = copy.deepcopy(_example())
    change(section)
    return {SECTION: section}


def _settings_from(config_directory: Path, profiles: str):
    """The e2e settings as the harness bootstraps them from its resolver
    variables, over a config directory holding the repository's base and
    `local` profile files beside whatever the test places there."""
    for name in ("config.yml", "config-local.yml"):
        shutil.copy(CONFIG / name, config_directory / name)
    return settings_module._load_bootstrap(
        {"CONFIG_DIRECTORY": str(config_directory), "ACTIVE_PROFILES": profiles}
    ).settings


def test_the_example_loads_through_its_profile_and_validates(tmp_path: Path):
    shutil.copy(EXAMPLE, tmp_path / PROFILE_FILE)
    settings = _settings_from(tmp_path, f"local,{PROFILE}")
    # The local profile's own settings are still there beside the target.
    assert settings.SELLER.API_URL == "http://localhost:8001"
    target = load_real_vm_target(settings)
    assert isinstance(target, RealVmTarget)
    assert target.version == 1
    assert target.host.host_id == "example-kvm-1"
    assert target.host.ssh_port == 22
    assert (target.host.capacity.vcpu_count, target.host.capacity.ram_gb,
            target.host.capacity.disk_gb) == (7, 28, 160)
    assert target.access.mode == "direct"


def test_without_the_profile_there_is_no_target(tmp_path: Path):
    shutil.copy(EXAMPLE, tmp_path / PROFILE_FILE)
    result = load_real_vm_target(_settings_from(tmp_path, "local"))
    assert isinstance(result, TargetNotConfigured)
    assert PROFILE in result.reason and PROFILE_FILE in result.reason


def test_a_selected_profile_without_its_file_has_no_target(tmp_path: Path):
    result = load_real_vm_target(_settings_from(tmp_path, f"local,{PROFILE}"))
    assert isinstance(result, TargetNotConfigured)


def test_an_absent_section_names_the_profile_and_file():
    result = load_real_vm_target({})
    assert isinstance(result, TargetNotConfigured)
    assert f"'{PROFILE}'" in result.reason
    assert PROFILE_FILE in result.reason


def test_an_empty_section_is_refused_rather_than_skipped(tmp_path: Path):
    (tmp_path / PROFILE_FILE).write_text(f"{SECTION}:\n")
    with pytest.raises(TargetInvalid, match=f"{SECTION} is NoneType, not a mapping"):
        load_real_vm_target(_settings_from(tmp_path, f"local,{PROFILE}"))


@pytest.mark.parametrize(
    ("change", "field"),
    [
        (lambda s: s["host"].pop("ssh_user"), f"{SECTION}.host.ssh_user"),
        (lambda s: s["host"].update(ssh_usr=s["host"].pop("ssh_user")),
         f"{SECTION}.host.ssh_usr"),
        (lambda s: s["host"]["capacity"].update(gpu_count=1),
         f"{SECTION}.host.capacity.gpu_count"),
        (lambda s: s.update(hosts=[]), f"{SECTION}.hosts"),
        (lambda s: s.pop("access"), f"{SECTION}.access"),
    ],
    ids=["missing", "misspelled", "unknown-nested", "unknown-top", "missing-section"],
)
def test_a_missing_or_unknown_field_is_refused_by_name(change, field):
    with pytest.raises(TargetInvalid) as refused:
        load_real_vm_target(_with(change))
    assert f"{field}:" in str(refused.value)


@pytest.mark.parametrize("version", [2, 0, "1", True, 1.0, None])
def test_an_unknown_version_is_refused_rather_than_interpreted(version):
    with pytest.raises(TargetInvalid) as refused:
        load_real_vm_target(_with(lambda s: s.update(version=version)))
    assert f"{SECTION}.version is {version!r}" in str(refused.value)


def test_relay_access_is_refused_under_version_1():
    with pytest.raises(TargetInvalid) as refused:
        load_real_vm_target(_with(lambda s: s["access"].update(mode="relay")))
    assert f"{SECTION}.access.mode:" in str(refused.value)


def test_a_section_without_a_version_is_refused_for_it():
    with pytest.raises(TargetInvalid, match=f"{SECTION}.version is None"):
        load_real_vm_target(_with(lambda s: s.pop("version")))


@pytest.mark.parametrize("value", [0, -4, "7", 7.5])
@pytest.mark.parametrize("dimension", ["vcpu_count", "ram_gb", "disk_gb"])
def test_capacity_is_a_positive_whole_number(dimension, value):
    with pytest.raises(TargetInvalid) as refused:
        load_real_vm_target(
            _with(lambda s: s["host"]["capacity"].update({dimension: value}))
        )
    assert f"{SECTION}.host.capacity.{dimension}:" in str(refused.value)


def test_a_section_that_is_not_a_mapping_is_refused():
    with pytest.raises(TargetInvalid, match="not a mapping"):
        load_real_vm_target({SECTION: ["example-kvm-1"]})
