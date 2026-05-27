from __future__ import annotations

import os
import subprocess
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def multipass_script() -> Path:
    return repo_root() / "scripts" / "clean-room" / "multipass-run.sh"


def test_multipass_dry_run_prints_clean_room_plan_without_multipass(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.update(
        {
            "PATH": env.get("PATH", ""),
            "SCM_MULTIPASS_NAME": "scm-dry-run-test",
            "SCM_MULTIPASS_ARTIFACT_DEST": str(tmp_path / "artifacts"),
        }
    )

    result = subprocess.run(
        [str(multipass_script()), "--dry-run"],
        cwd=repo_root(),
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert "dry run only; multipass will not be invoked" in result.stdout
    assert "clean-room sequence: local-vm" in result.stdout
    assert "SCM_CLEAN_ROOM_SEQUENCE=local-vm" in result.stdout
    assert "scm-dry-run-test" in result.stdout


def test_multipass_wrapper_delegates_sequence_to_bootstrap() -> None:
    script = multipass_script().read_text(encoding="utf-8")

    assert "SCM_CLEAN_ROOM_SEQUENCE" in script
    assert "SCM_VALIDATION_COMMAND" not in script
    assert "local_stack_build_without_zerotier" not in script
    assert "redis_no_host_port" not in script
    assert "storefront_volume_chown" not in script
