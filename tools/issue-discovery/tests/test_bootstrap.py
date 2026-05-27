from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def make_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def make_fake_path(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("bash", "cut", "dirname", "getent", "pwd"):
        target = shutil.which(tool)
        assert target is not None, tool
        os.symlink(target, bin_dir / tool)
    for tool in ("curl", "git", "jq", "make", "python3", "uv"):
        make_executable(bin_dir / tool, "#!/usr/bin/env bash\nexit 0\n")
    make_executable(
        bin_dir / "docker",
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$BOOTSTRAP_DOCKER_LOG"
if [ "${1:-}" = "compose" ] && [ "${2:-}" = "version" ]; then
  exit 0
fi
if [ "${1:-}" = "info" ]; then
  exit "${BOOTSTRAP_DOCKER_INFO_EXIT:-0}"
fi
exit 1
""",
    )
    return bin_dir


def bootstrap_env(tmp_path: Path, *, skip_zerotier: str = "1") -> dict[str, str]:
    bin_dir = make_fake_path(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "PATH": str(bin_dir),
            "BOOTSTRAP_DOCKER_LOG": str(tmp_path / "docker.log"),
            "SCM_BOOTSTRAP_SKIP_ZEROTIER": skip_zerotier,
        }
    )
    return env


def test_bootstrap_check_verifies_docker_daemon_access(tmp_path: Path) -> None:
    env = bootstrap_env(tmp_path, skip_zerotier="1")

    result = subprocess.run(
        [str(repo_root() / "scripts" / "bootstrap-clean-host-ubuntu.sh"), "check"],
        cwd=repo_root(),
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    docker_calls = (tmp_path / "docker.log").read_text(encoding="utf-8").splitlines()
    assert "compose version" in docker_calls
    assert "info" in docker_calls


def test_bootstrap_check_requires_zerotier_unless_skipped(tmp_path: Path) -> None:
    env = bootstrap_env(tmp_path, skip_zerotier="0")

    result = subprocess.run(
        [str(repo_root() / "scripts" / "bootstrap-clean-host-ubuntu.sh"), "check"],
        cwd=repo_root(),
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
