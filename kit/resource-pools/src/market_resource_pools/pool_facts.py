"""The facts of a stored pool, as the site authority's pool-facts port asks for them.

A site authority decides on whether a pool exists, whether it is enabled, the
offering modes it delivers, and whether its declarations need a host, and reads
them through a port it defines and its composition root fills.
``ResourcePoolFacts`` answers that port from the ``resource_pools`` table. The
port is structural, the values it returns included, so this module answers it
with its own ``StoredPoolFacts`` and imports nothing from the site authority:
the edge runs from the composition root to both, never between them.
"""

from __future__ import annotations

from dataclasses import dataclass

from market_resource_pools_contracts import declared_deliverable_modes
from sqlalchemy.orm import Session

from .db import ResourcePool
from .host_requirement import HostRequirement, pool_needs_host


@dataclass(frozen=True)
class StoredPoolFacts:
    """One pool's facts as ``ResourcePoolFacts`` read them."""

    exists: bool
    enabled: bool
    #: ``None`` when the pool's deliverable-mode declaration cannot be read, as
    #: for a missing pool.
    deliverable_modes: frozenset[str] | None
    needs_host: bool


class ResourcePoolFacts:
    """Reads a pool's facts from its stored row, in the caller's session.

    ``host_requirement`` is the composition's map from provider identity to
    whether that provider's declarations must name a host; with none supplied,
    no pool needs a host (``pool_needs_host``).
    """

    def __init__(self, host_requirement: HostRequirement | None = None) -> None:
        self.host_requirement = host_requirement

    def pool_facts(self, db: Session, pool_id: str) -> StoredPoolFacts:
        """The facts of pool ``pool_id``, read in ``db``.

        Read in the caller's session, so a decision sees the pool state its own
        transaction sees, its own uncommitted writes included. A pool with no
        row is reported as not existing, not enabled, with unreadable
        deliverable modes, and needing a host exactly when a requirement is
        supplied, so every decision refuses it. A stored declaration that does
        not parse reads as unreadable rather than raising: startup and every
        pool write refuse one, so a decision never meets it, and refusing is
        the safe answer if it ever did.
        """
        pool = db.get(ResourcePool, pool_id)
        if pool is None:
            return StoredPoolFacts(
                exists=False,
                enabled=False,
                deliverable_modes=None,
                needs_host=pool_needs_host(None, self.host_requirement),
            )
        try:
            modes: frozenset[str] | None = declared_deliverable_modes(
                pool.policy_tags or {}
            )
        except ValueError:
            modes = None
        return StoredPoolFacts(
            exists=True,
            enabled=bool(pool.enabled),
            deliverable_modes=modes,
            needs_host=pool_needs_host(pool.provider, self.host_requirement),
        )
