from __future__ import annotations

from pathlib import Path
import os
import subprocess

import typer

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_AGENT_ENV = REPO_ROOT / "core" / "agent" / ".env"


def read_env_value(env_file: str | Path | None, key: str, default: str = "") -> str:
    """Read a single KEY=value from an env file, returning default if absent."""
    if not env_file:
        return default
    path = Path(env_file)
    if not path.exists():
        return default
    try:
        for raw_line in path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() != key:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            return value
    except Exception:
        return default
    return default


def container_db_to_host(db_path: str) -> Path:
    """Resolve a container-side AGENT_DB_PATH to its host-side equivalent under REPO_ROOT.

    Container paths are relative to the container WORKDIR (/app), e.g.:
      ./core/agent/app/data/buy-agent/agent.db  →  REPO_ROOT/core/agent/app/data/buy-agent/agent.db
      /app/core/agent/app/data/buy-agent/agent.db  →  same

    With the -v mount added by `market start`, the file is accessible at this
    host path without needing docker exec.
    """
    rel = db_path
    if rel.startswith("/app/"):
        rel = rel[len("/app/"):]
    elif rel.startswith("./"):
        rel = rel[2:]
    return REPO_ROOT / rel


def run_step(
    label: str,
    cmd: list[str],
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> None:
    typer.echo(f"==> {label} at {cwd}")
    env = os.environ.copy()
    venv_path = cwd / ".venv"
    # TODO(refactor): After migration completes, always prefer core/.venv.
    # Transitional rule: commands run from core/agent should use core/.venv.
    if cwd.resolve() == (REPO_ROOT / "core" / "agent").resolve():
        core_venv = REPO_ROOT / "core" / ".venv"
        if core_venv.exists():
            venv_path = core_venv
    venv_bin = venv_path / "bin"
    if venv_bin.exists():
        env["VIRTUAL_ENV"] = str(venv_path)
        env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
    if extra_env:
        env.update(extra_env)
    subprocess.run(cmd, cwd=cwd, check=True, env=env)
