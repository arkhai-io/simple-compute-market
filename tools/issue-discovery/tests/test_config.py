from __future__ import annotations

from pathlib import Path

import pytest
from jsonschema import ValidationError

from issue_discovery.config import ToolPaths, load_yaml, validate_config
from issue_discovery.phases import load_phase_file
from issue_discovery.runner import _select_phases
from issue_discovery.workarounds import load_workarounds


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_tracked_configs_match_schemas() -> None:
    paths = ToolPaths(repo_root())
    cases = [
        (paths.config_dir / "phases" / "local.yaml", paths.schema_dir / "phases.schema.json"),
        (
            paths.config_dir / "phases" / "clean_ubuntu_bootstrap.yaml",
            paths.schema_dir / "phases.schema.json",
        ),
        (
            paths.config_dir / "phases" / "targeted_repros.yaml",
            paths.schema_dir / "phases.schema.json",
        ),
        (paths.config_dir / "collectors.yaml", paths.schema_dir / "collectors.schema.json"),
        (paths.config_dir / "profiles.yaml", paths.schema_dir / "profiles.schema.json"),
        (paths.config_dir / "workarounds.yaml", paths.schema_dir / "workarounds.schema.json"),
        (paths.config_dir / "redactions.yaml", paths.schema_dir / "redactions.schema.json"),
        (
            paths.config_dir / "clean-room" / "local-vm.yaml",
            paths.schema_dir / "clean-room.schema.json",
        ),
    ]

    for config_path, schema_path in cases:
        validate_config(config_path, schema_path)


def test_local_phase_file_loads_expected_core_phases() -> None:
    paths = ToolPaths(repo_root())
    phase_file = load_phase_file(paths.config_dir / "phases" / "local.yaml")
    ids = [phase.id for phase in phase_file.phases]

    assert phase_file.schema_version == 1
    assert ids[0] == "source_identity"
    assert "compose_start_strict" in ids
    assert "full_integration_sweep" in ids
    assert ids[-1] == "teardown"


def test_phase_ids_are_unique() -> None:
    paths = ToolPaths(repo_root())
    phase_file = load_phase_file(paths.config_dir / "phases" / "local.yaml")
    ids = [phase.id for phase in phase_file.phases]

    assert len(ids) == len(set(ids))


def test_profiles_expand_required_dependencies_in_order() -> None:
    paths = ToolPaths(repo_root())
    profiles = load_yaml(paths.config_dir / "profiles.yaml")["profiles"]

    for profile in profiles:
        phase_file = load_phase_file(paths.config_dir / profile["phase_file"])
        phases = _select_phases(phase_file, tuple(profile["phases"]))
        seen: set[str] = set()
        for phase in phases:
            assert set(phase.requires).issubset(seen), profile["id"]
            seen.add(phase.id)
        assert set(profile["phases"]).issubset(seen)


def test_build_phase_can_use_explicit_continuation_command() -> None:
    paths = ToolPaths(repo_root())
    phase_file = load_phase_file(paths.config_dir / "phases" / "local.yaml")
    build = next(phase for phase in phase_file.phases if phase.id == "build")
    workarounds = load_workarounds(paths.config_dir / "workarounds.yaml")

    assert build.commands[0].run == "${ISSUE_DISCOVERY_BUILD_COMMAND:-make build}"
    assert "local_stack_build_without_zerotier" in workarounds
    assert "ISSUE_DISCOVERY_BUILD_COMMAND" in workarounds["local_stack_build_without_zerotier"].env
    assert workarounds["local_stack_build_without_zerotier"].start_phase == "build"
    assert workarounds["redis_no_host_port"].start_phase == "compose_preexisting_stack_check"
    assert workarounds["storefront_volume_chown"].start_phase == "compose_start_strict"


def test_clean_room_local_vm_sequence_is_laddered() -> None:
    paths = ToolPaths(repo_root())
    config = load_yaml(paths.config_dir / "clean-room" / "local-vm.yaml")
    sequences = {sequence["id"]: sequence for sequence in config["sequences"]}
    steps = sequences["local-vm"]["steps"]

    assert steps[0]["mode"] == "strict"
    assert "workarounds" not in steps[0]
    assert [step["workarounds"] for step in steps[1:]] == [
        ["local_stack_build_without_zerotier"],
        ["local_stack_build_without_zerotier", "redis_no_host_port"],
        [
            "local_stack_build_without_zerotier",
            "redis_no_host_port",
            "storefront_volume_chown",
        ],
    ]
    assert all(step["continue_on_failure"] for step in steps)
    assert not any("run" in step or "command" in step or "commands" in step for step in steps)


def test_targeted_repro_profiles_are_minimal_and_explicit() -> None:
    paths = ToolPaths(repo_root())
    profiles = {profile["id"]: profile for profile in load_yaml(paths.config_dir / "profiles.yaml")["profiles"]}

    assert set(["host-redis-conflict", "fresh-volumes", "zerotier-build-path"]).issubset(profiles)
    assert profiles["host-redis-conflict"]["phase_file"] == "phases/targeted_repros.yaml"
    assert profiles["fresh-volumes"]["phase_file"] == "phases/targeted_repros.yaml"
    assert profiles["zerotier-build-path"]["phase_file"] == "phases/targeted_repros.yaml"
    assert profiles["host-redis-conflict"]["phases"] == [
        "source_identity",
        "host_identity",
        "redis_port_conflict_setup",
        "compose_preexisting_stack_check",
        "compose_start_strict",
        "redis_port_conflict_cleanup",
        "teardown",
    ]
    assert profiles["fresh-volumes"]["phases"] == [
        "source_identity",
        "host_identity",
        "redis_no_host_port_override",
        "fresh_volume_reset",
        "compose_preexisting_stack_check",
        "compose_start_strict",
        "readiness_checks",
        "teardown",
    ]
    assert profiles["fresh-volumes"]["env"] == {
        "ISSUE_DISCOVERY_COMPOSE_ARGS": "-f docker-compose.yml -f /tmp/scm-no-redis-port.yml"
    }
    assert profiles["zerotier-build-path"]["phases"] == [
        "source_identity",
        "host_identity",
        "zerotier_build_path",
    ]


@pytest.mark.parametrize(
    "bad_yaml",
    [
        """
schema_version: 1
sequences:
  - id: bad
    steps:
      - id: unknown
        mode: repair
        continue_on_failure: true
""",
        """
schema_version: 1
sequences:
  - id: bad
    steps:
      - id: empty-continuation
        mode: continue
        workarounds: []
        continue_on_failure: true
""",
        """
schema_version: 1
sequences:
  - id: bad
    steps:
      - id: embedded-shell
        mode: continue
        workarounds:
          - redis_no_host_port
        commands:
          - docker compose up
        continue_on_failure: true
""",
    ],
)
def test_clean_room_schema_rejects_invalid_sequence_steps(tmp_path: Path, bad_yaml: str) -> None:
    paths = ToolPaths(repo_root())
    config_path = tmp_path / "bad-clean-room.yaml"
    config_path.write_text(bad_yaml.lstrip(), encoding="utf-8")

    with pytest.raises(ValidationError):
        validate_config(config_path, paths.schema_dir / "clean-room.schema.json")
