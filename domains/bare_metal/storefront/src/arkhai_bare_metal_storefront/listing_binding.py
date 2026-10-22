"""A bare-metal listing's capacity binding, built from its durable record."""

from __future__ import annotations

from typing import Any

from arkhai_bare_metal import BARE_METAL_OFFERING_MODE
from market_capacity_publication import (
    CapacityBindingError,
    PublicationBinding,
    publication_binding,
)


async def bare_metal_listing_binding(
    repository: Any, listing_id: str
) -> PublicationBinding | None:
    """The listing's binding, whose source is the Physical Resource it offers.

    A bare-metal listing sells one specific machine, so its binding's source
    is that Physical Resource rather than its pool; the pool stays part of
    the listing's derivation key. Built from the durable record alone, with
    the backing it recorded, for publication and every capacity effect alike.
    ``repository`` is the storefront's persistence, read through its
    ``load_listing_binding``.
    """
    durable = await repository.load_listing_binding(listing_id=listing_id)
    if durable is None or not durable.physical_resource_id:
        return None
    if durable.binding.offering_mode != BARE_METAL_OFFERING_MODE:
        raise CapacityBindingError(
            f"listing {listing_id!r} is not bound as a bare-metal listing"
        )
    return publication_binding(
        capacity_backing=durable.capacity_backing,
        site_id=durable.site_id,
        offering_mode=BARE_METAL_OFFERING_MODE,
        source_id=durable.physical_resource_id,
    )


__all__ = ["bare_metal_listing_binding"]
