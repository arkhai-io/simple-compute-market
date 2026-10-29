"""Bare metal's view in the site's resource-pool projection: one whole machine.

A capacity declaration whose ``bare_metal_publication`` attribute enables it is
published as a machine for sale under ``bare_metal.v2``, the view a bare-metal
storefront derives its listing from. The attribute itself is the view's source,
so it is consumed here and left out of the declaration's neutral attributes.

The view's delivery terms -- the host, the physical host, access methods, and
whether the whole machine is available -- pass through the pool's backing
delegate, so a backed pool's view carries them and an unbacked pool's carries
none, whatever the declaration names. The view is then validated through the
carrier a storefront reads it with, under the pool's backing, so the site never
emits a view its readers refuse. A declaration from which no valid view can be
built projects without one and with the reasons, rather than failing the
site's whole projection.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from arkhai_bare_metal import BareMetalResourceProjection, TrustedBareMetalResource
from arkhai_bare_metal.publication import BARE_METAL_PUBLICATION_VIEW
from compute_provisioning import InventoryPoolContext, ResourceViews
from pydantic import ValidationError

#: The declaration attribute that configures a machine's publication.
BARE_METAL_PUBLICATION_ATTR = "bare_metal_publication"


def project_bare_metal_resource(
    raw_view: Mapping[str, Any], *, pool: InventoryPoolContext
) -> dict[str, Any]:
    """Validate the public bare-metal resource projection and serialize it.

    Validated as a storefront reads it: as a member of ``pool``, held to its
    backing. Raises ``ValidationError`` for a view no reader would accept.
    """
    view = BareMetalResourceProjection.model_validate(raw_view)
    TrustedBareMetalResource(
        pool_id=pool.pool_id,
        enabled=True,
        view=view,
        capacity_backing=pool.declarations.backing.label,
    )
    # A term the backing does not carry is absent from the wire, not null.
    return view.model_dump(mode="json", exclude_none=True)


def _problems(error: ValidationError) -> tuple[str, ...]:
    return tuple(
        f"{'.'.join(str(part) for part in detail['loc'])}: {detail['msg']}"
        if detail["loc"]
        else detail["msg"]
        for detail in error.errors()
    )


class BareMetalPublicationViews:
    """The ``bare_metal.v2`` view of each declaration that enables publication."""

    resource_view_ids = frozenset({BARE_METAL_PUBLICATION_VIEW})
    pool_view_ids: frozenset[str] = frozenset()
    consumed_attributes = frozenset({BARE_METAL_PUBLICATION_ATTR})

    def resource_views(
        self, declaration: Mapping[str, Any], *, pool: InventoryPoolContext
    ) -> ResourceViews:
        attributes = dict(declaration.get("attributes") or {})
        config = attributes.get(BARE_METAL_PUBLICATION_ATTR)
        if not isinstance(config, Mapping) or not config.get("enabled", False):
            return ResourceViews()

        capacity = dict(declaration.get("capacity") or {})
        available = dict(declaration.get("available") or {})
        host_id = declaration.get("host_id")
        physical_host_id = attributes.get("physical_host_id")
        # Identity and cross-mode accounting come from the declaration itself
        # -- its host field and the attributes the ledger's cross-mode rule
        # reads -- so the view cannot name a different machine than admission
        # accounts for. Whether the view carries them is the backing's.
        terms = pool.declarations.backing.carry_delivery_terms(
            {
                "host_id": str(host_id) if host_id else None,
                "physical_host_id": str(physical_host_id) if physical_host_id else None,
                "access_methods": config.get("access_methods"),
                "available": (
                    bool(declaration.get("enabled", True))
                    and whole_resource_available(capacity, available)
                ),
            }
        )
        try:
            # The view is a self-contained public projection, so it carries the
            # pool it belongs to rather than leaving a consumer to recover it
            # from the enclosing resource.
            view = project_bare_metal_resource(
                {
                    "physical_resource_id": str(declaration.get("resource_id") or ""),
                    "pool_id": pool.pool_id,
                    **terms,
                    "allocation_mode": attributes.get("allocation_mode"),
                    "capacity": capacity,
                    "capabilities": config.get("capabilities") or {},
                },
                pool=pool,
            )
        except ValidationError as exc:
            return ResourceViews(problems={BARE_METAL_PUBLICATION_VIEW: _problems(exc)})
        return ResourceViews(views={BARE_METAL_PUBLICATION_VIEW: view})

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
