from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess

import typer

_PKG_DIR = Path(__file__).resolve().parent
_BUNDLED_DIR = _PKG_DIR / "_bundled"
_WORKSPACE_DIR = Path.home() / ".market"
_VERSION = "0.1.0"


def _resolve_workspace() -> Path:
    """Return the workspace root where service directories live.

    Dev/editable install: __file__ is at <repo>/cli/market/common.py so
    parents[2] is the repo root containing agent/, cli/, etc.

    Wheel install: _bundled/ exists inside the installed package; extract
    it to ~/.market on first run or version mismatch, preserving .env files.
    """
    dev_root = _PKG_DIR.resolve().parents[1]
    if (dev_root / "agent").is_dir() and (dev_root / "cli").is_dir():
        return dev_root

    # Wheel install path — extract bundled payload to ~/.market
    if not _BUNDLED_DIR.is_dir():
        raise RuntimeError(
            "market CLI: neither a dev checkout nor a bundled wheel detected"
        )

    version_file = _WORKSPACE_DIR / ".version"
    needs_extract = (
        not _WORKSPACE_DIR.exists()
        or not version_file.exists()
        or version_file.read_text().strip() != _VERSION
    )

    if needs_extract:
        # Collect existing .env files to preserve across updates
        saved_envs: dict[str, str] = {}
        if _WORKSPACE_DIR.exists():
            for env_file in _WORKSPACE_DIR.rglob(".env"):
                rel = env_file.relative_to(_WORKSPACE_DIR)
                saved_envs[str(rel)] = env_file.read_text()
            shutil.rmtree(_WORKSPACE_DIR)

        shutil.copytree(_BUNDLED_DIR, _WORKSPACE_DIR)

        # Restore .env files
        for rel_path, content in saved_envs.items():
            dest = _WORKSPACE_DIR / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)

        version_file.write_text(_VERSION)
        typer.echo(f"Extracted market workspace to {_WORKSPACE_DIR}")

    return _WORKSPACE_DIR


REPO_ROOT = _resolve_workspace()


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
