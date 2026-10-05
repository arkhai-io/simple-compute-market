"""Domain views in the site's resource-pool projection, contributed by adapters.

The projection a site serves is neutral: every capacity declaration and every
pool, as declared. A domain that publishes something more, such as a view of a
whole machine it sells or a pool's configured defaults, contributes an
``InventoryViewProjection``. The projection names the views it produces and the
declaration attributes it reads for them; the service merges what each
projection returns and never names a domain's view, attribute, or provider
configuration, so a further compute domain adds its views without changing the
service.

A view is attached where the wire carries it: a resource view under a projected
resource's ``publication_views``, a pool view under a pool's ``pool_views``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol


class InventoryViewProjection(Protocol):
    """What one domain adds to the resource-pool projection.

    ``resource_view_ids`` and ``pool_view_ids`` are every view identifier the
    projection may return, at each attachment point. ``consumed_attributes``
    are the declaration attributes it publishes through a view, which the
    neutral projection therefore omits. Either method returns only the views
    that apply, possibly none.
    """

    resource_view_ids: frozenset[str]
    pool_view_ids: frozenset[str]
    consumed_attributes: frozenset[str]

    def resource_views(
        self, declaration: Mapping[str, Any], *, pool_id: str
    ) -> Mapping[str, Mapping[str, Any]]:
        """Views of one capacity declaration, which belongs to ``pool_id``."""

    def pool_views(
        self, db: Any, *, pool_id: str, provider: str
    ) -> Mapping[str, Mapping[str, Any]]:
        """Views of one pool, read in the projection's own session ``db``."""


@dataclass(frozen=True)
class InventoryViews:
    """Every contributed projection, checked to be unambiguous."""

    projections: tuple[InventoryViewProjection, ...] = ()

    @property
    def consumed_attributes(self) -> frozenset[str]:
        return frozenset().union(*(p.consumed_attributes for p in self.projections))

    def resource_views(
        self, declaration: Mapping[str, Any], *, pool_id: str
    ) -> dict[str, dict[str, Any]]:
        views: dict[str, dict[str, Any]] = {}
        for projection in self.projections:
            produced = projection.resource_views(declaration, pool_id=pool_id)
            _check_declared(projection, produced, projection.resource_view_ids)
            views.update({view_id: dict(view) for view_id, view in produced.items()})
        return views

    def pool_views(
        self, db: Any, *, pool_id: str, provider: str
    ) -> dict[str, dict[str, Any]]:
        views: dict[str, dict[str, Any]] = {}
        for projection in self.projections:
            produced = projection.pool_views(db, pool_id=pool_id, provider=provider)
            _check_declared(projection, produced, projection.pool_view_ids)
            views.update({view_id: dict(view) for view_id, view in produced.items()})
        return views


def _check_declared(
    projection: InventoryViewProjection,
    produced: Mapping[str, Any],
    declared: frozenset[str],
) -> None:
    # Composition refuses overlaps only among declared identifiers, so a view
    # the projection never declared could silently replace another domain's.
    undeclared = sorted(set(produced) - declared)
    if undeclared:
        raise ValueError(
            f"inventory projection {type(projection).__name__} produced undeclared "
            f"view(s): {', '.join(undeclared)}"
        )


def compose_inventory_views(
    owned: Iterable[tuple[str, InventoryViewProjection]],
) -> InventoryViews:
    """Check contributed projections and return them composed.

    ``owned`` pairs each projection with the bundle contributing it. A view
    identifier at the same attachment point, or a consumed attribute, claimed
    by two projections is refused: either would let one domain's view replace
    or hide another's.
    """
    owners: dict[tuple[str, str], str] = {}
    projections: list[InventoryViewProjection] = []
    for bundle_name, projection in owned:
        claims = (
            [("resource view", view_id) for view_id in projection.resource_view_ids]
            + [("pool view", view_id) for view_id in projection.pool_view_ids]
            + [("consumed attribute", name) for name in projection.consumed_attributes]
        )
        for claim in claims:
            previous = owners.get(claim)
            if previous is not None:
                raise ValueError(
                    f"duplicate inventory {claim[0]} {claim[1]!r}: "
                    f"bundles {previous!r} and {bundle_name!r}"
                )
            owners[claim] = bundle_name
        projections.append(projection)
    return InventoryViews(tuple(projections))


__all__ = [
    "InventoryViewProjection",
    "InventoryViews",
    "compose_inventory_views",
]
