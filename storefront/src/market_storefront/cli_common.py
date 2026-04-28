"""CLI helpers for the storefront's `market-storefront` console script.

Env-file parsing, container-path translation, and venv-aware subprocess
wrappers — mirroring buyer/market_buyer/common.py. The HTTP and auth
helpers used to live here too, but were superseded by the
storefront-client SDK; only the local-orchestration helpers remain.
"""

from __future__ import annotations

from pathlib import Path
import os
import subprocess

import typer

# parents[3]: market_storefront → src → storefront → repo root
REPO_ROOT = Path(__file__).resolve().parents[3]

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
    toml_path: str | None = None,
    default: str = "",
) -> str:
    """Lookup a scalar config value: CLI override > config.toml > default."""
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
      ./src/market_storefront/data/sell-agent/agent.db  →  REPO_ROOT/src/market_storefront/data/sell-agent/agent.db
      /app/src/market_storefront/data/sell-agent/agent.db  →  same
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
    """Resolve the URL the CLI should dial to reach the storefront.

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


def _resolve_db_path(db: str | None) -> str | None:
    """Return the SQLite DB path from explicit ``--db`` or
    ``seller.db_path`` in config.toml."""
    if db:
        return db
    from service.config_loader import get_dotted, load_user_config
    cfg = load_user_config()
    toml_db = get_dotted(cfg, "seller.db_path")
    if isinstance(toml_db, str) and toml_db and Path(toml_db).exists():
        return toml_db
    return None


def run_step(
    label: str,
    cmd: list[str],
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> None:
    typer.echo(f"==> {label} at {cwd}")
    env = os.environ.copy()
    venv_path = cwd / ".venv"
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
