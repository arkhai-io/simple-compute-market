"""Bare-metal-domain interpretation of the domain-neutral `listing_mode` hint.

Bare-metal listings are inherently one machine each -- there is no pooled
concept for `derived_bare_metal_listings` to formalize the way VM's
fungible-vs-specific-resource split does. This resolver exists only for
symmetry with the VM domain's own resolver (`domains.vms.listings.listing_mode`)
and to give an unrecognized `listing_mode` value the same operator-visible,
non-fatal handling VM's resolver gives it, rather than silently ignoring it.
"""

from __future__ import annotations

from typing import Any, Literal, Mapping

from market_resource_pools.hints import raw_listing_mode

BareMetalListingMode = Literal["specific_resource"]

_DEFAULT_BARE_METAL_LISTING_MODE: BareMetalListingMode = "specific_resource"


def resolve_bare_metal_listing_mode(
    policy_tags: Mapping[str, Any],
) -> tuple[BareMetalListingMode, str | None]:
    """Always resolves to `specific_resource` -- see module docstring."""
    raw = raw_listing_mode(policy_tags)
    if raw is None or raw == _DEFAULT_BARE_METAL_LISTING_MODE:
        return _DEFAULT_BARE_METAL_LISTING_MODE, None
    return (
        _DEFAULT_BARE_METAL_LISTING_MODE,
        f"unrecognized listing_mode {raw!r} for bare metal, "
        f"using {_DEFAULT_BARE_METAL_LISTING_MODE!r}",
    )
