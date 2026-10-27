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

A resource view is built with its pool's context, since what a view may carry
can depend on the pool's declarations -- its backing among them. A projection
never raises on a declaration's content: declarations reach the site from any
client, and one that a view builder could not handle would otherwise fail the
site's whole projection. It returns instead why it could not build a view,
which the projected resource carries as ``publication_view_problems``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from market_resource_pools_contracts.hints import PoolDeclarations


@dataclass(frozen=True)
class InventoryPoolContext:
    """The pool a capacity declaration belongs to, as a resource view sees it.

    ``declarations`` are the pool's resolved advertisement and backing
    declarations; the service that builds the context resolves them and
    interprets none of them.
    """

    pool_id: str
    provider: str
    declarations: PoolDeclarations


@dataclass(frozen=True)
class ResourceViews:
    """What one projection built from one declaration.

    ``views`` maps each view built to its content; ``problems`` maps each view
    it declares but could not build to why, one message per reason.
    """

    views: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    problems: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


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
        self, declaration: Mapping[str, Any], *, pool: InventoryPoolContext
    ) -> ResourceViews:
        """Views of one capacity declaration in ``pool``, and the problems that
        kept any declared view from being built. Never raises on the
        declaration's content."""

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
        self, declaration: Mapping[str, Any], *, pool: InventoryPoolContext
    ) -> ResourceViews:
        views: dict[str, dict[str, Any]] = {}
        problems: dict[str, tuple[str, ...]] = {}
        for projection in self.projections:
            produced = projection.resource_views(declaration, pool=pool)
            _check_declared(projection, produced.views, projection.resource_view_ids)
            _check_declared(projection, produced.problems, projection.resource_view_ids)
            both = sorted(set(produced.views) & set(produced.problems))
            if both:
                # A view is either built or not; reporting both leaves a reader
                # no way to tell which to believe.
                raise ValueError(
                    f"inventory projection {type(projection).__name__} produced "
                    f"view(s) and problems for the same view: {', '.join(both)}"
                )
            views.update(
                {view_id: dict(view) for view_id, view in produced.views.items()}
            )
            problems.update(
                {view_id: tuple(found) for view_id, found in produced.problems.items()}
            )
        return ResourceViews(views=views, problems=problems)

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
    "InventoryPoolContext",
    "InventoryViewProjection",
    "InventoryViews",
    "ResourceViews",
    "compose_inventory_views",
]
