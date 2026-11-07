"""CLI helpers for the storefront's `market-storefront` console script.

Storefront URL resolution, the administrator client, container-path
translation, and venv-aware subprocess wrappers, shared across the per-group
CLI modules. Configuration is read from TOML by the commands that need it.
"""

from __future__ import annotations

from pathlib import Path
import os
import subprocess

import httpx
import typer
from market_identity import TrustedIdentitySet
from storefront_client import StorefrontClientError, SyncStorefrontClient

# parents[2]: market_storefront -> src -> storefront
STOREFRONT_ROOT = Path(__file__).resolve().parents[2]


def _find_repo_root() -> Path:
    """Best-effort monorepo root: nearest ancestor with the repo markers.

    In the container image the package lives at /app/src/... with no
    repo checkout above it; fall back to the filesystem root so import
    succeeds — REPO_ROOT consumers are dev-machine conveniences (the
    zerotier scripts path) that don't apply in-container.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "domains").is_dir() and (parent / "kit").is_dir():
            return parent
    return here.parents[-1]


REPO_ROOT = _find_repo_root()

#: What a command that calls the storefront reports and exits on, rather than
#: a traceback: the storefront's refusal, or no storefront answering at all.
STOREFRONT_FAILURES: tuple[type[Exception], ...] = (
    StorefrontClientError,
    httpx.TransportError,
)


def storefront_failure_message(exc: Exception) -> str:
    """The line a command prints for one of ``STOREFRONT_FAILURES``.

    A request no storefront answered names the scheme, host, and port it was
    sent to and the transport error's type.
    """
    if not isinstance(exc, httpx.TransportError):
        return f"Storefront error: {exc}"
    try:
        url = exc.request.url
    except RuntimeError:
        origin = "the storefront URL"
    else:
        port = f":{url.port}" if url.port is not None else ""
        origin = f"{url.scheme}://{url.host}{port}"
    return f"Storefront error: no storefront answered at {origin} ({type(exc).__name__})"


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


def admin_client(base_url: str) -> SyncStorefrontClient:
    """A client signing as the storefront's own administrator.

    Administrator routes authenticate a principal the storefront pins under
    `identity.administrators`, so the storefront's own signer must be
    configured there for a command using this client to act.
    """
    # Resolving the signer loads the storefront's settings, which only a
    # command that talks to the storefront needs.
    from .utils.config import resolve_marketplace_signer

    signer = resolve_marketplace_signer()
    return SyncStorefrontClient(
        base_url,
        signer=signer,
        caller_role="admin",
        expected_publishers=TrustedIdentitySet(identities=(signer.identity,)),
    )


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
    if cwd.resolve() == STOREFRONT_ROOT.resolve():
        storefront_venv = STOREFRONT_ROOT / ".venv"
        if storefront_venv.exists():
            venv_path = storefront_venv
    venv_bin = venv_path / "bin"
    if venv_bin.exists():
        env["VIRTUAL_ENV"] = str(venv_path)
        env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
    if extra_env:
        env.update(extra_env)
    subprocess.run(cmd, cwd=cwd, check=True, env=env)
