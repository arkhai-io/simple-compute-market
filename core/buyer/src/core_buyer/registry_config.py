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


#: Per-process cache of each registry's declared schema id. The value is
#: the declared ``schema.id`` string, or None when the registry declares
#: nothing (pre-identity deployment) or the spec fetch failed — both of
#: which match any plugin, so they cache identically.
_SCHEMA_ID_CACHE: dict[str, str | None] = {}


def reset_schema_id_cache() -> None:
    """Drop the per-process schema-id cache — for tests."""
    _SCHEMA_ID_CACHE.clear()


def registry_schema_id(
    url: str,
    *,
    timeout: float | None = None,
    api_key: str | None = None,
) -> str | None:
    """The schema id a registry declares in its ``/filter-spec``.

    Returns None when the registry declares no schema identity or the
    spec cannot be fetched/parsed — lenient by design: an undeclared or
    momentarily unreachable registry must not vanish from discovery
    (the listings query itself will fail loudly if the registry is
    truly down). Cached per process; the CLI is one-shot.
    """
    key = url.rstrip("/")
    if key in _SCHEMA_ID_CACHE:
        return _SCHEMA_ID_CACHE[key]

    import json
    import urllib.request

    declared: str | None = None
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(key + "/filter-spec", headers=headers)
    try:
        with urllib.request.urlopen(
            req, timeout=timeout if timeout and timeout > 0 else resolve_discovery_timeout(),
        ) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        schema = body.get("schema") if isinstance(body, dict) else None
        if isinstance(schema, dict) and str(schema.get("id") or "").strip():
            declared = str(schema["id"]).strip()
    except Exception:  # noqa: BLE001 — lenient: treat as undeclared
        declared = None

    _SCHEMA_ID_CACHE[key] = declared
    return declared


def resolve_indexer_urls_for_schema(
    schema_id: str,
    *,
    override: str | None = None,
    timeout: float | None = None,
) -> list[str]:
    """The configured registry URLs that serve ``schema_id``.

    Resolves the registry list (CLI override > config > default), then
    drops any registry whose ``/filter-spec`` *declares a different*
    schema id. Registries declaring nothing — and registries whose spec
    can't be fetched — are kept: only an explicit mismatch excludes,
    so single-registry setups and pre-identity registries behave as
    before. A dropped registry is reported on stderr so a buyer staring
    at "no matches" can see why a configured registry wasn't asked.

    A singleton list is returned without fetching anything: filtering
    chooses *among* registries, and with one configured there is no
    choice to make — dropping it would leave nothing to query, and the
    lenient rule queries it regardless, so the spec fetch would be pure
    overhead on the most common deployment.
    """
    import sys

    urls = resolve_indexer_urls(override=override)
    if len(urls) <= 1:
        return urls
    auth = resolve_indexer_auth()
    kept: list[str] = []
    for url in urls:
        declared = registry_schema_id(url, timeout=timeout, api_key=auth.get(url))
        if declared is not None and declared != schema_id:
            print(
                f"[registry] skipping {url}: serves schema {declared!r}, "
                f"not {schema_id!r}",
                file=sys.stderr,
            )
            continue
        kept.append(url)
    return kept


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
