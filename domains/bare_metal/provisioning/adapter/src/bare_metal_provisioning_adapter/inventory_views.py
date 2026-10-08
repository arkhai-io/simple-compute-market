"""Bare metal's view in the site's resource-pool projection: one whole machine.

A capacity declaration whose ``bare_metal_publication`` attribute enables it is
published as a machine for sale under ``bare_metal.v2``, the view a bare-metal
storefront derives its listing from. The attribute itself is the view's source,
so it is consumed here and left out of the declaration's neutral attributes.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from arkhai_bare_metal import BareMetalResourceProjection
from arkhai_bare_metal.publication import BARE_METAL_PUBLICATION_VIEW

#: The declaration attribute that configures a machine's publication.
BARE_METAL_PUBLICATION_ATTR = "bare_metal_publication"


def project_bare_metal_resource(raw_view: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and serialize the public bare-metal resource projection."""
    return BareMetalResourceProjection.model_validate(raw_view).model_dump(mode="json")


class BareMetalPublicationViews:
    """The ``bare_metal.v2`` view of each declaration that enables publication."""

    resource_view_ids = frozenset({BARE_METAL_PUBLICATION_VIEW})
    pool_view_ids: frozenset[str] = frozenset()
    consumed_attributes = frozenset({BARE_METAL_PUBLICATION_ATTR})

    def resource_views(
        self, declaration: Mapping[str, Any], *, pool_id: str
    ) -> Mapping[str, Mapping[str, Any]]:
        attributes = dict(declaration.get("attributes") or {})
        config = attributes.get(BARE_METAL_PUBLICATION_ATTR)
        if not isinstance(config, Mapping) or not config.get("enabled", False):
            return {}
        host_id = declaration.get("host_id")
        if not host_id:
            # The view sells one specific host. A declaration naming none has
            # nothing to sell as one, so it projects without the view; failing
            # instead would take every other declaration at the site out of the
            # projection with it.
            return {}

        capacity = dict(declaration.get("capacity") or {})
        available = dict(declaration.get("available") or {})
        # The view is a self-contained public projection, so it carries the
        # pool it belongs to rather than leaving a consumer to recover it from
        # the enclosing resource.
        view = project_bare_metal_resource({
            "physical_resource_id": str(declaration.get("resource_id") or ""),
            "pool_id": pool_id,
            # Identity and cross-mode accounting come from the declaration
            # itself -- its host field and the attributes the ledger's
            # cross-mode rule reads -- so the view cannot name a different
            # machine than admission accounts for.
            "physical_host_id": str(attributes.get("physical_host_id") or ""),
            "host_id": str(host_id),
            "available": (
                bool(declaration.get("enabled", True))
                and whole_resource_available(capacity, available)
            ),
            "allocation_mode": str(attributes.get("allocation_mode") or ""),
            "access_methods": list(config.get("access_methods") or []),
            "capacity": capacity,
            "capabilities": dict(config.get("capabilities") or {}),
        })
        return {BARE_METAL_PUBLICATION_VIEW: view}

    def pool_views(
        self, db: Any, *, pool_id: str, provider: str
    ) -> Mapping[str, Mapping[str, Any]]:
        return {}


def whole_resource_available(
    capacity: Mapping[str, Any],
    available: Mapping[str, Any],
) -> bool:
    """Whether every positive capacity dimension remains wholly available.

    A machine is sold whole, so it is available only while nothing of it is
    held; a declaration with no positive dimension has nothing to sell.
    """
    compared = False
    for key, raw_total in capacity.items():
        try:
            total = Decimal(str(raw_total))
            remaining = Decimal(str(available.get(key, 0)))
        except (InvalidOperation, TypeError, ValueError):
            return False
        if not total.is_finite() or not remaining.is_finite() or total < 0:
            return False
        if total > 0:
            compared = True
            if remaining < total:
                return False
    return compared


__all__ = [
    "BARE_METAL_PUBLICATION_ATTR",
    "BareMetalPublicationViews",
    "project_bare_metal_resource",
    "whole_resource_available",
]
