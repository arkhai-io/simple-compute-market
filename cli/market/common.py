from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess

import typer

from importlib.metadata import version as pkg_version, PackageNotFoundError

_BUNDLED_DIR = Path(__file__).resolve().parent / "_bundled"
_WORKSPACE_DIR = Path.home() / ".market"


def _get_installed_version() -> str:
    try:
        return pkg_version("market-cli")
    except PackageNotFoundError:
        return "unknown"


def _init_workspace(workspace: Path) -> None:
    """Extract bundled data to the workspace directory, preserving .env files."""
    if not _BUNDLED_DIR.exists():
        raise RuntimeError(
            f"Bundled data not found at {_BUNDLED_DIR}. "
            "Please reinstall market-cli: pip install --upgrade market-cli"
        )

    # Back up existing .env files
    env_backups: dict[str, str] = {}
    if workspace.exists():
        for env_file in workspace.rglob(".env"):
            rel = str(env_file.relative_to(workspace))
            env_backups[rel] = env_file.read_text(encoding="utf-8")

    # Copy bundled data to workspace
    if workspace.exists():
        # Remove everything except .env files, then copy fresh
        shutil.rmtree(workspace)
    shutil.copytree(_BUNDLED_DIR, workspace)

    # Restore .env files
    for rel, content in env_backups.items():
        target = workspace / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    # Write version marker
    (workspace / ".version").write_text(
        _get_installed_version(), encoding="utf-8"
    )


def _get_repo_root() -> Path:
    """Resolve the root directory containing all service components.

    In dev mode (editable install from the repo), this returns the repo root.
    In installed mode (pip install from PyPI), this returns ~/.market/ and
    auto-extracts bundled data on first run or version mismatch.
    """
    # Check if running from a dev/editable install (repo checkout)
    dev_root = Path(__file__).resolve().parents[2]
    if (dev_root / "agent").is_dir() and (dev_root / "cli").is_dir():
        return dev_root

    # Running from a regular install — use workspace
    current_version = _get_installed_version()
    version_file = _WORKSPACE_DIR / ".version"

    needs_init = (
        not _WORKSPACE_DIR.exists()
        or not version_file.exists()
        or version_file.read_text(encoding="utf-8").strip() != current_version
    )

    if needs_init:
        _init_workspace(_WORKSPACE_DIR)

    return _WORKSPACE_DIR


REPO_ROOT = _get_repo_root()


def run_step(
    label: str,
    cmd: list[str],
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> None:
    typer.echo(f"==> {label} at {cwd}")
    env = os.environ.copy()
    venv_path = cwd / ".venv"
    venv_bin = venv_path / "bin"
    if venv_bin.exists():
        env["VIRTUAL_ENV"] = str(venv_path)
        env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
    if extra_env:
        env.update(extra_env)
    subprocess.run(cmd, cwd=cwd, check=True, env=env)
