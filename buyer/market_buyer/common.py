from __future__ import annotations

from pathlib import Path
import os
import subprocess

import typer

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_AGENT_ENV = REPO_ROOT / "storefront" / ".env"


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
    *,
    override: str | None = None,
    env_file: str | Path | None = None,
    env_name: str | None = None,
    toml_path: str | None = None,
    default: str = "",
) -> str:
    """One-stop lookup for a scalar config value across our sources.

    Precedence:
      1. Explicit ``override`` (CLI flag)
      2. ``env_file`` value (only when the user explicitly passed ``--env``;
         these files are dev-time helpers, not the runtime config surface)
      3. Dotted ``toml_path`` key in the user config.toml
      4. ``default``

    Process env vars are intentionally not consulted — config flows
    through TOML or explicit CLI args. ``env_name`` is kept (optional)
    only as the key lookup name for the explicit ``env_file`` step.
    """
    if override:
        return override
    if env_file and env_name:
        v = read_env_value(env_file, env_name)
        if v:
            return v
    if toml_path:
        from service.config_loader import get_dotted, load_user_config
        v = get_dotted(load_user_config(), toml_path)
        if v not in (None, ""):
            return str(v)
    return default


def container_db_to_host(db_path: str) -> Path:
    """Resolve a container-side AGENT_DB_PATH to its host-side equivalent under REPO_ROOT.

    Container paths are relative to the container WORKDIR (/app), e.g.:
      ./src/market_storefront/data/buy-agent/agent.db  →  REPO_ROOT/src/market_storefront/data/buy-agent/agent.db
      /app/src/market_storefront/data/buy-agent/agent.db  →  same

    With the -v mount added by `market start`, the file is accessible
    at this host path without needing docker exec.
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
      1. Explicit ``--agent-url`` flag (passed as ``agent_url``).
      2. If the env file declares ``AGENT_MODE=container``:
         ``http://localhost:{PORT}``. ``BASE_URL_OVERRIDE`` in container
         env files points at the docker-internal hostname (e.g.
         ``http://buy_agent:8000/``), which is unreachable from the
         host — never use it as a CLI target.
      3. Env-file ``BASE_URL_OVERRIDE`` (host mode).
      4. ``http://localhost:{default_port}``.

    Process env vars are not consulted — config flows through CLI args
    or TOML, not ambient env.
    """
    if agent_url:
        return agent_url
    env_path = Path(env_file) if env_file else None
    agent_mode = read_env_value(env_path, "AGENT_MODE", default="host") if env_path else "host"
    port = read_env_value(env_path, "PORT", default=str(default_port)) if env_path else str(default_port)
    if agent_mode == "container":
        return f"http://localhost:{port}"
    env_url = read_env_value(env_path, "BASE_URL_OVERRIDE") if env_path else None
    return env_url or f"http://localhost:{default_port}"


def run_step(
    label: str,
    cmd: list[str],
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> None:
    typer.echo(f"==> {label} at {cwd}")
    env = os.environ.copy()
    venv_path = cwd / ".venv"
    # When running storefront-side commands (e.g. registration scripts)
    # the working dir is the storefront package, but uv created the
    # venv at the storefront package root.
    if cwd.resolve() == (REPO_ROOT / "storefront").resolve():
        storefront_venv = REPO_ROOT / "storefront" / ".venv"
        if storefront_venv.exists():
            venv_path = storefront_venv
    venv_bin = venv_path / "bin"
    if venv_bin.exists():
        env["VIRTUAL_ENV"] = str(venv_path)
        env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
    if extra_env:
        env.update(extra_env)
    subprocess.run(cmd, cwd=cwd, check=True, env=env)
