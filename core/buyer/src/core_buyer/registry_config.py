"""Generic registry discovery configuration for the buyer role.

These resolvers carry no schema vocabulary — they answer "which registries,
with what credentials, under what deadline" from the buyer's TOML config
(via ``market_config``) with CLI overrides taking precedence. Schema
plugins and the core generic commands share them.
"""

from __future__ import annotations
from dataclasses import dataclass


from market_identity import Identity, Signer, TrustedIdentitySet
from registry_client import SyncRegistryClient


@dataclass(frozen=True)
class RegistryAuthority:
    """Stable registry authority id and its ordered active signer set."""

    authority: str
    principals: TrustedIdentitySet


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
        parts = [p.strip().rstrip("/") for p in override.split(",") if p.strip()]
        if parts:
            return parts
    from market_config.config_loader import get_dotted, load_user_config

    raw = get_dotted(load_user_config(), "registry.urls")
    if isinstance(raw, list) and raw:
        cleaned = [str(u).strip().rstrip("/") for u in raw if str(u).strip()]
        if cleaned:
            return cleaned
    return ["http://localhost:8080"]


def resolve_registry_authorities(
    registry_urls: list[str],
) -> dict[str, RegistryAuthority]:
    """Resolve exact URL-scoped stable authorities and active trust sets."""

    from market_config.config_loader import get_dotted, load_user_config

    raw = get_dotted(load_user_config(), "registry.authorities")
    if not isinstance(raw, dict) or not raw:
        raise RuntimeError("Missing required [registry.authorities] identity pins")
    pins: dict[str, RegistryAuthority] = {}
    for raw_url, raw_authority in raw.items():
        if not isinstance(raw_url, str) or not raw_url.strip():
            raise RuntimeError("[registry.authorities] contains an invalid URL key")
        url = raw_url.strip().rstrip("/")
        if url in pins:
            raise RuntimeError(
                f"[registry.authorities] contains duplicate normalized URL {url!r}"
            )
        try:
            if not isinstance(raw_authority, dict) or set(raw_authority) != {
                "authority",
                "identities",
            }:
                raise ValueError(
                    "authority entry must contain authority and identities"
                )
            authority = raw_authority["authority"]
            if not isinstance(authority, str) or not authority.strip():
                raise ValueError("authority must be nonempty text")
            raw_identities = raw_authority["identities"]
            if not isinstance(raw_identities, (list, tuple)):
                raise ValueError("identities must be an array")
            principals = TrustedIdentitySet(
                identities=tuple(
                    Identity.model_validate(identity) for identity in raw_identities
                )
            )
            pins[url] = RegistryAuthority(
                authority=authority.strip(),
                principals=principals,
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"[registry.authorities] contains an invalid authority for {url!r}"
            ) from exc
    expected_urls = {url.rstrip("/") for url in registry_urls}
    configured_urls = set(pins)
    if configured_urls != expected_urls:
        missing = sorted(expected_urls - configured_urls)
        extra = sorted(configured_urls - expected_urls)
        raise RuntimeError(
            "[registry.authorities] must exactly match registry.urls "
            f"(missing={missing}, extra={extra})"
        )
    return pins


def resolve_registry_api_keys() -> dict[str, str]:
    """Resolve optional bearer authorization in addition to signed identity."""

    from market_config.config_loader import get_dotted, load_user_config

    raw = get_dotted(load_user_config(), "registry.auth")
    if not isinstance(raw, dict):
        return {}
    return {
        url.strip().rstrip("/"): token.strip()
        for url, token in raw.items()
        if isinstance(url, str)
        and isinstance(token, str)
        and url.strip()
        and token.strip()
    }


#: Per-process cache of each pinned registry's declared schema id.
_SCHEMA_ID_CACHE: dict[tuple[str, TrustedIdentitySet], str | None] = {}


def reset_schema_id_cache() -> None:
    """Drop the per-process schema-id cache — for tests."""
    _SCHEMA_ID_CACHE.clear()


def registry_schema_id(
    url: str,
    *,
    signer: Signer,
    registry_authority: RegistryAuthority,
    timeout: float | None = None,
    api_key: str | None = None,
) -> str | None:
    """Read a schema id through a signed, authority-pinned filter-spec request."""

    base_url = url.rstrip("/")
    key = (base_url, registry_authority.principals)
    if key in _SCHEMA_ID_CACHE:
        return _SCHEMA_ID_CACHE[key]
    try:
        with SyncRegistryClient(
            base_url,
            signer=signer,
            caller_role="buyer",
            expected_registries=registry_authority.principals,
            registry_authority=registry_authority.authority,
            timeout=(
                timeout
                if timeout is not None and timeout > 0
                else resolve_discovery_timeout()
            ),
            api_key=api_key,
        ) as client:
            declared = client.get_filter_spec().schema_id
    except Exception:
        declared = None
    _SCHEMA_ID_CACHE[key] = declared
    return declared


def resolve_indexer_urls_for_schema(
    schema_id: str,
    *,
    signer: Signer,
    registry_authorities: dict[str, RegistryAuthority],
    override: str | None = None,
    timeout: float | None = None,
) -> list[str]:
    """Return registry URLs compatible with a schema through signed inspection."""

    import sys

    urls = resolve_indexer_urls(override=override)
    if set(registry_authorities) != set(urls):
        raise RuntimeError(
            "registry authority trust sets must exactly match registry URLs"
        )
    if len(urls) <= 1:
        return urls
    api_keys = resolve_registry_api_keys()
    kept: list[str] = []
    for url in urls:
        declared = registry_schema_id(
            url,
            signer=signer,
            registry_authority=registry_authorities[url],
            timeout=timeout,
            api_key=api_keys.get(url),
        )
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
