from __future__ import annotations

from pathlib import Path
import os
import subprocess

import typer

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_AGENT_ENV = REPO_ROOT / "storefront" / ".env"


def resolve_config_value(
    *,
    override: str | None = None,
    toml_path: str | None = None,
    default: str = "",
) -> str:
    """Lookup a scalar config value: CLI override > config.toml > default.

    The TOML file location is whatever ``service.config_loader.load_user_config``
    resolves to (XDG default, or the override set by ``--config``).
    """
    if override:
        return override
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
    default_port: int = 8000,
) -> str:
    """Resolve the URL the CLI should dial to reach the agent.

    Precedence: explicit ``agent_url`` > ``seller.base_url`` from
    config.toml > ``http://localhost:{default_port}``.
    """
    if agent_url:
        return agent_url
    from service.config_loader import get_dotted, load_user_config
    cfg = load_user_config()
    base_url = get_dotted(cfg, "seller.base_url")
    if isinstance(base_url, str) and base_url:
        return base_url
    return f"http://localhost:{default_port}"


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
