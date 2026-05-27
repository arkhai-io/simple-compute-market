from __future__ import annotations

from pathlib import Path

from issue_discovery.clean_room import (
    load_clean_room_sequence,
    render_clean_room_script,
    render_step_command,
)
from issue_discovery.config import ToolPaths


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_load_clean_room_sequence_reads_laddered_steps() -> None:
    paths = ToolPaths(repo_root())

    sequence = load_clean_room_sequence(paths.config_dir / "clean-room" / "local-vm.yaml", "local-vm")

    assert sequence.id == "local-vm"
    assert [step.id for step in sequence.steps] == [
        "strict",
        "continue-build-without-zerotier",
        "continue-build-and-redis",
        "continue-build-redis-and-storefront-volume",
    ]
    assert sequence.steps[0].mode == "strict"
    assert sequence.steps[0].workarounds == ()
    assert sequence.steps[-1].workarounds == (
        "local_stack_build_without_zerotier",
        "redis_no_host_port",
        "storefront_volume_chown",
    )


def test_render_step_command_uses_issue_discovery_workaround_ids() -> None:
    paths = ToolPaths(repo_root())
    sequence = load_clean_room_sequence(paths.config_dir / "clean-room" / "local-vm.yaml", "local-vm")

    assert render_step_command(sequence.steps[0]) == (
        "./scripts/issue-discovery",
        "strict",
    )
    assert render_step_command(sequence.steps[-1]) == (
        "./scripts/issue-discovery",
        "continue",
        "--with",
        "local_stack_build_without_zerotier",
        "--with",
        "redis_no_host_port",
        "--with",
        "storefront_volume_chown",
    )


def test_render_clean_room_script_records_exit_codes_and_continues() -> None:
    paths = ToolPaths(repo_root())
    sequence = load_clean_room_sequence(paths.config_dir / "clean-room" / "local-vm.yaml", "local-vm")

    script = render_clean_room_script(sequence)

    assert "set -e" not in script
    assert "SCM_CLEAN_ROOM_STATUS_FILE" in script
    assert 'printf \'%s\\t%s\\n\' "$step_id" "$rc" >> "$status_file"' in script
    assert (
        "run_step strict true ./scripts/issue-discovery strict"
        in script
    )
    assert (
        "run_step continue-build-redis-and-storefront-volume true "
        "./scripts/issue-discovery continue --with local_stack_build_without_zerotier "
        "--with redis_no_host_port --with storefront_volume_chown"
        in script
    )


def test_render_clean_room_script_does_not_embed_workaround_implementation() -> None:
    paths = ToolPaths(repo_root())
    sequence = load_clean_room_sequence(paths.config_dir / "clean-room" / "local-vm.yaml", "local-vm")

    script = render_clean_room_script(sequence)

    assert "docker compose" not in script
    assert "docker run" not in script
    assert "chown -R" not in script
    assert "cat >" not in script
    assert "install.zerotier.com" not in script
