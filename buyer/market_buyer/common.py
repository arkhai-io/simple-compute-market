from __future__ import annotations

from pathlib import Path
import os
import subprocess

import typer

REPO_ROOT = Path(__file__).resolve().parents[2]


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


def resolve_ssh_public_key(*, override: str | None = None) -> str:
    """Resolve the buyer's SSH public key for provisioning.

    Precedence: explicit override > ``wallet.ssh_public_key`` from config.toml
    > the first standard public-key file found in ``~/.ssh/``. Returns an
    empty string if no source has one — the caller decides whether that's
    fatal (settle requires it; reclaim/refund don't).

    The ~/.ssh fallback covers the most common case where the user has an
    ed25519/rsa keypair but never added it to config.toml. Order matches
    OpenSSH's identity-file default search order.
    """
    explicit = resolve_config_value(override=override, toml_path="wallet.ssh_public_key")
    if explicit:
        return explicit
    home_ssh = Path.home() / ".ssh"
    for fname in ("id_ed25519.pub", "id_ecdsa.pub", "id_rsa.pub"):
        p = home_ssh / fname
        if p.is_file():
            try:
                content = p.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if content:
                return content
    return ""


def resolve_indexer_urls(*, override: str | None = None) -> list[str]:
    """Resolve the buyer's configured registry URLs as a list.

    Precedence: CLI override (comma-separated) > ``registry.urls`` (list)
    > ``http://localhost:8080`` default. Mirrors the storefront's
    ``_resolve_indexer_urls`` shape — only the plural list form is
    recognised, so a stray scalar ``registry.url`` falls through to
    the default.

    The override is comma-separated rather than a repeatable typer
    option because every command that takes it already declares a
    single string flag; comma-splitting keeps the change to those
    declarations a one-liner.
    """
    if override:
        parts = [p.strip() for p in override.split(",") if p.strip()]
        if parts:
            return parts
    from service.config_loader import get_dotted, load_user_config
    raw = get_dotted(load_user_config(), "registry.urls")
    if isinstance(raw, list) and raw:
        cleaned = [str(u).strip() for u in raw if str(u).strip()]
        if cleaned:
            return cleaned
    return ["http://localhost:8080"]


def resolve_indexer_auth() -> dict[str, str]:
    """Resolve per-registry bearer tokens from the buyer's TOML config.

    Reads ``[registry.auth]``, a flat ``url → token`` table. URLs not
    listed are queried unauthenticated. There is no CLI override —
    credentials are config-only by design (avoids accidental shell-
    history exposure on a multi-user box).
    """
    from service.config_loader import get_dotted, load_user_config
    raw = get_dotted(load_user_config(), "registry.auth")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for url, token in raw.items():
        if isinstance(url, str) and isinstance(token, str) and url.strip() and token.strip():
            out[url.strip()] = token.strip()
    return out


def resolve_discovery_timeout(*, override: float | None = None) -> float:
    """Resolve the buyer's per-registry discovery deadline (seconds).

    Precedence: CLI override > ``registry.discovery_timeout`` from
    config.toml > ``5.0``. The orchestrator's multi-URL helpers cap
    each per-registry request at this value so a slow registry can't
    extend the wall time of a discovery pass.
    """
    if override is not None and override > 0:
        return float(override)
    from service.config_loader import get_dotted, load_user_config
    raw = get_dotted(load_user_config(), "registry.discovery_timeout")
    try:
        v = float(raw)
        if v > 0:
            return v
    except (TypeError, ValueError):
        pass
    return 5.0


def resolve_default_token() -> str:
    """Pick the buyer's default token symbol for `--token-contract` resolution.

    Looks up `buyer.default_token` in the user config; falls back to ``"MOCK"``
    so behavior is unchanged for unconfigured installs. The symbol is resolved
    against ``service.clients.token.TOKEN_REGISTRY`` at the call site.
    """
    from service.config_loader import get_dotted, load_user_config
    v = get_dotted(load_user_config(), "buyer.default_token")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return "MOCK"


def resolve_storefront_url(
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
