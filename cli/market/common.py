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


def resolve_config_value(
    env_name: str,
    *,
    override: str | None = None,
    env_file: str | Path | None = None,
    toml_path: str | None = None,
    default: str = "",
) -> str:
    """One-stop lookup for a scalar config value across all our sources.

    Precedence:
      1. Explicit `override` (CLI flag)
      2. `env_file` (e.g. core/agent/.env passed via --env)
      3. Shell `env_name` environment variable
      4. Dotted `toml_path` key in the user config.toml
      5. `default`

    Centralized so every CLI command gets the same hierarchy without
    duplicating a _resolve block. Keeps the existing --env file flow
    working while adding the TOML-config fallback beneath it.
    """
    if override:
        return override
    if env_file:
        v = read_env_value(env_file, env_name)
        if v:
            return v
    v = os.environ.get(env_name)
    if v:
        return v
    if toml_path:
        from .config_loader import get_dotted, load_user_config
        v = get_dotted(load_user_config(), toml_path)
        if v not in (None, ""):
            return str(v)
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


def resolve_agent_url(
    agent_url: str | None,
    env_file: str | Path | None,
    default_port: int = 8000,
) -> str:
    """Resolve the URL the CLI should dial to reach the agent.

    Precedence:
      1. Explicit --agent-url flag (passed in as `agent_url`).
      2. If the env file declares AGENT_MODE=container: `http://localhost:{PORT}`.
         BASE_URL_OVERRIDE in container env files points at the docker-internal
         hostname (e.g. `http://buy_agent:8000/`), which is unreachable from
         the host — never use it as a CLI target.
      3. Env-file BASE_URL_OVERRIDE (host mode).
      4. Process-env AGENT_URL / BASE_URL_OVERRIDE.
      5. `http://localhost:{default_port}`.
    """
    if agent_url:
        return agent_url
    env_path = Path(env_file) if env_file else None
    agent_mode = read_env_value(env_path, "AGENT_MODE", default="host") if env_path else "host"
    port = read_env_value(env_path, "PORT", default=str(default_port)) if env_path else str(default_port)
    if agent_mode == "container":
        return f"http://localhost:{port}"
    env_url = read_env_value(env_path, "BASE_URL_OVERRIDE") if env_path else None
    return (
        env_url
        or os.getenv("AGENT_URL")
        or os.getenv("BASE_URL_OVERRIDE")
        or f"http://localhost:{default_port}"
    )


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
