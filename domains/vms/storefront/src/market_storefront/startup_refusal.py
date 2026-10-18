"""Configuration the storefront refuses to start under.

Two kinds of problem stop the storefront before it opens its database or starts
a loop, each reported under its own heading with every problem of that kind
named:

- a retired setting it still states: a renamed one, which would otherwise run
  at a default the operator did not choose, or a removed one, which the
  storefront no longer honours (`market_storefront.retired_settings`);
- a configuration under which it could never publish, because a storefront
  that only services deals it has already accepted is not a supported
  deployment: no registry to publish to, or one without its authority pin; no
  enabled settlement mechanism; or no configured site, or a site not bound to
  exactly one service peer.

Terms that a pool's override or hint may supply instead of the storefront's
defaults -- its settlement clauses among them -- are not checked here: a pool
that resolves none is held and reported by publication. See the requirement
"A storefront that cannot publish refuses to start" in
openspec/specs/storefront-publication/spec.md.
"""

from __future__ import annotations

from dynaconf import Dynaconf

from core_storefront.service_peers import require_one_service_peer_per_site

from market_storefront.retired_settings import (
    REMOVED_SETTINGS,
    RENAMED_SETTINGS,
    retired_setting_explanation,
)
from market_storefront.settlement_registry import build_storefront_settlement_registry
from market_storefront.utils.config import (
    configured_capacity_sites,
    get_registry_authorities,
    get_service_peer_configs,
    settings,
    settlement_config_mapping,
)

RETIRED_SETTINGS_HEADING = "the storefront states retired settings"
CANNOT_PUBLISH_HEADING = "the storefront cannot publish"


class StorefrontStartupError(RuntimeError):
    """The storefront's configuration states a retired setting or leaves it
    unable to publish."""


def retired_setting_problems(source: Dynaconf | None = None) -> list[str]:
    """Name each renamed or removed setting the configuration still states,
    in any spelling, with what replaces it."""

    active = settings if source is None else source
    return [
        retired_setting_explanation(key)
        for key in (*RENAMED_SETTINGS, *REMOVED_SETTINGS)
        if active.get(key) is not None
    ]


def _registry_problems(source: Dynaconf) -> list[str]:
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
        *_registry_problems(active),
        *_settlement_problems(active),
        *_site_problems(active),
    ]


def require_publishable_storefront(source: Dynaconf | None = None) -> None:
    """Refuse to start, naming each problem under its heading, when the
    configuration states a retired setting or leaves publication impossible."""
    active = settings if source is None else source
    sections = [
        f"{heading}: " + "; ".join(problems)
        for heading, problems in (
            (RETIRED_SETTINGS_HEADING, retired_setting_problems(active)),
            (CANNOT_PUBLISH_HEADING, publication_startup_problems(active)),
        )
        if problems
    ]
    if sections:
        raise StorefrontStartupError(". ".join(sections))


__all__ = [
    "CANNOT_PUBLISH_HEADING",
    "RETIRED_SETTINGS_HEADING",
    "StorefrontStartupError",
    "publication_startup_problems",
    "require_publishable_storefront",
    "retired_setting_problems",
]
