from __future__ import annotations

from pathlib import Path

from issue_discovery.config import ToolPaths, validate_config
from issue_discovery.phases import load_phase_file


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
        (paths.config_dir / "collectors.yaml", paths.schema_dir / "collectors.schema.json"),
        (paths.config_dir / "profiles.yaml", paths.schema_dir / "profiles.schema.json"),
        (paths.config_dir / "workarounds.yaml", paths.schema_dir / "workarounds.schema.json"),
        (paths.config_dir / "redactions.yaml", paths.schema_dir / "redactions.schema.json"),
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
