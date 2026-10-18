"""Configuration the bare-metal storefront refuses to start under.

A storefront that only services deals it has already accepted is not a
supported deployment, so the storefront refuses to start, before it opens its
database or starts a loop, when publication is impossible for the whole
storefront, naming every problem: no registry to publish to, or one without its
authority pin; no enabled settlement mechanism; or no configured site, or a site
not bound to exactly one service peer.

Terms a pool's override may supply instead of the storefront's defaults -- its
settlement clauses and its maximum lease duration -- are not checked here: a
pool that resolves none is held and reported by publication. See the
requirement "A storefront that cannot publish refuses to start" in
openspec/specs/storefront-publication/spec.md.
"""

from __future__ import annotations

from core_storefront.service_peers import require_one_service_peer_per_site

from .config import BareMetalConfigurationError, BareMetalStorefrontSettings
from .settlement_composition import build_bare_metal_settlement_registry

CANNOT_PUBLISH_HEADING = "the storefront cannot publish"


class BareMetalStartupError(RuntimeError):
    """The storefront's configuration leaves it unable to publish."""


def _registry_problems(settings: BareMetalStorefrontSettings) -> list[str]:
    if not settings.registry.urls:
        return ["no registry to publish to: [registry].urls is empty"]
    try:
        settings.registry_authorities()
    except BareMetalConfigurationError as exc:
        return [str(exc)]
    return []


def _settlement_problems(settings: BareMetalStorefrontSettings) -> list[str]:
    try:
        config = build_bare_metal_settlement_registry().resolve(
            settings.settlement, role="seller"
        )
    except ValueError as exc:
        return [f"[Settlement] cannot be resolved: {exc}"]
    if not any(getattr(section, "enabled", False) for section in config.mechanisms.values()):
        return ["no settlement mechanism is enabled under [Settlement]"]
    return []


def _site_problems(settings: BareMetalStorefrontSettings) -> list[str]:
    sites = settings.capacity.sites
    if not sites:
        return [
            "no site to publish from: [capacity.sites] must map each stable site ID "
            "to its authority URL"
        ]
    try:
        require_one_service_peer_per_site(settings.service_peer_configs(), sites)
    except ValueError as exc:
        return [f"[Identity.service_peers]: {exc}"]
    return []


def publication_startup_problems(settings: BareMetalStorefrontSettings) -> list[str]:
    """Every reason the configuration leaves publication impossible, in order."""
    return [
        *_registry_problems(settings),
        *_settlement_problems(settings),
        *_site_problems(settings),
    ]


def require_publishable_storefront(settings: BareMetalStorefrontSettings) -> None:
    """Refuse to start, naming each problem, when publication is impossible."""
    problems = publication_startup_problems(settings)
    if problems:
        raise BareMetalStartupError(f"{CANNOT_PUBLISH_HEADING}: " + "; ".join(problems))


__all__ = [
    "CANNOT_PUBLISH_HEADING",
    "BareMetalStartupError",
    "publication_startup_problems",
    "require_publishable_storefront",
]
