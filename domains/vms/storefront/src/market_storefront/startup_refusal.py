"""Configuration under which the storefront could never publish, refused at startup.

A storefront that only services deals it has already accepted is not a
supported deployment, so a configuration that leaves publication impossible for
the whole storefront stops it before it opens its database or starts a loop:
no registry to publish to, or one without its authority pin; no enabled
settlement mechanism; no configured site, or a site not bound to exactly one
service peer; or a setting stated under a name the storefront has renamed.

Terms that a pool's override or hint may supply instead of the storefront's
defaults -- its settlement clauses among them -- are not checked here: a pool
that resolves none is held and reported by publication. See the requirement "A
storefront that cannot publish refuses to start" in
openspec/specs/storefront-publication/spec.md.
"""

from __future__ import annotations

from dynaconf import Dynaconf

from core_storefront.service_peers import require_one_service_peer_per_site

from market_storefront.settlement_registry import build_storefront_settlement_registry
from market_storefront.utils.config import (
    configured_capacity_sites,
    get_registry_authorities,
    get_service_peer_configs,
    renamed_setting_problems,
    settings,
    settlement_config_mapping,
)


class StorefrontStartupError(RuntimeError):
    """The storefront's configuration leaves it unable to publish."""


def _registry_problems(source: Dynaconf) -> list[str]:
    # Publication to registries is switched by `enable_registry_discovery`;
    # with it off the storefront deliberately publishes nowhere.
    if not source.get("enable_registry_discovery", True):
        return []
    if not list(source.get("registry.urls") or []):
        return ["no registry to publish to: [registry].urls is empty"]
    try:
        get_registry_authorities(source)
    except ValueError as exc:
        return [f"[registry].authorities: {exc}"]
    return []


def _settlement_problems(source: Dynaconf) -> list[str]:
    try:
        config = build_storefront_settlement_registry().resolve(
            settlement_config_mapping(source), role="seller"
        )
    except ValueError as exc:
        return [f"[Settlement] cannot be resolved: {exc}"]
    if not any(getattr(section, "enabled", False) for section in config.mechanisms.values()):
        return ["no settlement mechanism is enabled under [Settlement]"]
    return []


def _site_problems(source: Dynaconf) -> list[str]:
    try:
        sites = configured_capacity_sites(source)
    except RuntimeError as exc:
        return [str(exc)]
    try:
        require_one_service_peer_per_site(get_service_peer_configs(source), sites)
    except ValueError as exc:
        return [f"[Identity.service_peers]: {exc}"]
    return []


def publication_startup_problems(source: Dynaconf | None = None) -> list[str]:
    """Every reason the configuration leaves publication impossible, in order."""
    active = settings if source is None else source
    return [
        *renamed_setting_problems(active),
        *_registry_problems(active),
        *_settlement_problems(active),
        *_site_problems(active),
    ]


def require_publishable_storefront(source: Dynaconf | None = None) -> None:
    """Refuse to start, naming each problem, when the storefront cannot publish."""
    problems = publication_startup_problems(source)
    if problems:
        raise StorefrontStartupError(
            "the storefront cannot publish: " + "; ".join(problems)
        )


__all__ = [
    "StorefrontStartupError",
    "publication_startup_problems",
    "require_publishable_storefront",
]
