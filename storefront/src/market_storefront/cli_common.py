"""CLI helpers for the storefront's `market-storefront` console script.

Container-path translation and venv-aware subprocess wrappers, used
across the per-group CLI modules. The env-file readers that used to
live here were retired with the TOML-only config migration; the
`register` / `serve` commands now read CONFIG directly.
"""

from __future__ import annotations

from pathlib import Path
import os
import subprocess

import typer

# parents[3]: market_storefront → src → storefront → repo root
REPO_ROOT = Path(__file__).resolve().parents[3]


def resolve_storefront_url(
    explicit_url: str | None,
    default_port: int = 8000,
) -> str:
    """Resolve the URL the CLI should dial to reach the storefront.

    Precedence: explicit ``--storefront-url`` > ``base_url`` from
    ``storefront.toml`` (the same file the server reads) > ``http://localhost:{default_port}``.
    """
    if explicit_url:
        return explicit_url
    from market_config.config_loader import get_dotted, load_storefront_config
    cfg = load_storefront_config()
    base_url = get_dotted(cfg, "base_url")
    if isinstance(base_url, str) and base_url:
        return base_url
    return f"http://localhost:{default_port}"


def _resolve_db_path(db: str | None) -> str | None:
    """Return the SQLite DB path from explicit ``--db`` or
    ``db_path`` in ``storefront.toml`` (same file the server reads)."""
    if db:
        return db
    from market_config.config_loader import get_dotted, load_storefront_config
    cfg = load_storefront_config()
    toml_db = get_dotted(cfg, "db_path")
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
