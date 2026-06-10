"""Generic registry discovery configuration for the buyer role.

These resolvers carry no schema vocabulary — they answer "which registries,
with what credentials, under what deadline" from the buyer's TOML config
(via ``market_config``) with CLI overrides taking precedence. Schema
plugins and the core generic commands share them.
"""

from __future__ import annotations


def resolve_indexer_urls(*, override: str | None = None) -> list[str]:
    """Resolve the buyer's configured registry URLs as a list.

    Precedence: CLI override (comma-separated) > ``registry.urls`` (list)
    > ``http://localhost:8080`` default. Only the plural list form is
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
    from market_config.config_loader import get_dotted, load_user_config
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
    from market_config.config_loader import get_dotted, load_user_config
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
    from market_config.config_loader import get_dotted, load_user_config
    raw = get_dotted(load_user_config(), "registry.discovery_timeout")
    try:
        v = float(raw)
        if v > 0:
            return v
    except (TypeError, ValueError):
        pass
    return 5.0
